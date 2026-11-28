// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

// TwinPALS M1: real Geant4 electromagnetic/optical transport of selected gamma ensembles.
// The analog PMT response follows optics. Source-clock/lifetime/acquisition belong to M2.
#include "analog_pmt.hpp"
#include "json.hpp"
#include "G4RunManager.hh"
#include "G4MTRunManager.hh"
#include "G4VUserActionInitialization.hh"
#include "G4UserWorkerInitialization.hh"
#include "G4Threading.hh"
#include "G4VUserDetectorConstruction.hh"
#include "G4VModularPhysicsList.hh"
#include "G4EmStandardPhysics_option4.hh"
#include "G4DecayPhysics.hh"
#include "G4OpticalPhysics.hh"
#include "G4OpticalParameters.hh"
#include "G4VUserPrimaryGeneratorAction.hh"
#include "G4UserEventAction.hh"
#include "G4UserSteppingAction.hh"
#include "G4UserTrackingAction.hh"
#include "G4VUserPrimaryParticleInformation.hh"
#include "G4VExceptionHandler.hh"
#include "G4StateManager.hh"
#include "G4UIsession.hh"
#include "G4UImanager.hh"
#include "G4NistManager.hh"
#include "G4Material.hh"
#include "G4MaterialPropertiesTable.hh"
#include "G4Box.hh"
#include "G4Tubs.hh"
#include "G4Cons.hh"
#include "G4Trd.hh"
#include "G4IonisParamMat.hh"
#include "G4SubtractionSolid.hh"
#include "G4LogicalVolume.hh"
#include "G4PVPlacement.hh"
#include "G4OpticalSurface.hh"
#include "G4LogicalBorderSurface.hh"
#include "G4TouchableHistory.hh"
#include "G4OpBoundaryProcess.hh"
#include "G4GeometryTolerance.hh"
#include "G4ParticleChange.hh"
#include "G4TransportationManager.hh"
#include "G4Navigator.hh"
#include "G4ProcessManager.hh"
#include "G4Gamma.hh"
#include "G4Electron.hh"
#include "G4OpticalPhoton.hh"
#include "G4PrimaryParticle.hh"
#include "G4PrimaryVertex.hh"
#include "G4Event.hh"
#include "G4Track.hh"
#include "G4Step.hh"
#include "G4SystemOfUnits.hh"
#include "G4PhysicalConstants.hh"
#include "G4Version.hh"
#include "Randomize.hh"
#include "CLHEP/Random/MixMaxRng.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <condition_variable>
#include <deque>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <sstream>
#include <string>
#include <string_view>
#include <thread>
#include <unordered_map>
#include <vector>

using json = nlohmann::json;
namespace fs = std::filesystem;
using Curve = std::vector<std::pair<double, double>>;
constexpr const char* kEngineVersion = "11.4.0";
constexpr const char* kWorkerVersion = TWINPALS_VERSION;
constexpr const char* kRngPolicy = "geant4-mt-per-event-mixmax-v1";
constexpr const char* kOpticalBoundaryModel = "geant4-11.4-lut-interior-v1";
constexpr std::size_t kReorderBytesLimit = 64 * 1024 * 1024;
constexpr std::size_t kEventBytesLimit = 32 * 1024 * 1024;
static std::size_t reorderEventLimit(int threads) {
    // Misses finish quickly; a rare optical event must not idle the other workers.
    // Keep enough lookahead for them to find work, with independent event/byte caps.
    return static_cast<std::size_t>(std::clamp(128 * threads, 256, 8192));
}
static std::mutex consoleMutex;
#ifndef G4MULTITHREADED
#error TwinPALS requires a multithreaded Geant4 build
#endif

static void emitProtocol(const json& message) {
    std::lock_guard<std::mutex> lock(consoleMutex);
    std::cout << message.dump() << std::endl;
}

// Display messages must not make the transport's ordered file writer wait for
// stdout on every sample. The bounded FIFO preserves every selected preview.
// A persistently stalled consumer eventually applies bounded backpressure.
class PreviewPublisher {
    std::mutex mutex;std::condition_variable ready;
    std::deque<std::string> messages;std::size_t bytes=0;
    bool closing=false,failed=false;
    std::thread worker;
    void send() noexcept {
        try {
            for(;;){
                std::string message;
                {
                    std::unique_lock<std::mutex> lock(mutex);
                    ready.wait(lock,[&]{return closing||!messages.empty();});
                    if(messages.empty())return;
                    message=std::move(messages.front());messages.pop_front();bytes-=message.size();ready.notify_all();
                }
                std::lock_guard<std::mutex> output(consoleMutex);
                std::cout<<message<<std::endl;
                if(!std::cout.good())throw std::runtime_error("Cannot publish preview");
            }
        } catch(...) {std::lock_guard<std::mutex> lock(mutex);failed=true;ready.notify_all();}
    }
public:
    PreviewPublisher():worker([this]{send();}){}
    ~PreviewPublisher(){close();}
    void push(const json& value){
        auto encoded=value.dump();
        std::unique_lock<std::mutex> lock(mutex);
        ready.wait(lock,[&]{return failed||messages.empty()||bytes+encoded.size()<=32*1024*1024;});
        if(failed||closing)throw std::runtime_error("Preview publication stopped");
        bytes+=encoded.size();messages.push_back(std::move(encoded));ready.notify_all();
    }
    void close() noexcept {
        {std::lock_guard<std::mutex> lock(mutex);closing=true;ready.notify_all();}
        if(worker.joinable())worker.join();
    }
    bool succeeded(){std::lock_guard<std::mutex> lock(mutex);return !failed;}
};

static void require(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}
static void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
static double number(const json& j, const char* name, double lo, double hi) {
    require(j.contains(name) && j.at(name).is_number(), std::string("Missing numeric field: ") + name);
    const double n = j.at(name).get<double>();
    require(std::isfinite(n) && n >= lo && n <= hi, std::string("Out-of-range field: ") + name);
    return n;
}
static double optionalNumber(const json& j, const char* name, double fallback, double lo, double hi) {
    return j.contains(name) ? number(j, name, lo, hi) : fallback;
}
static Curve curve(const json& data, const std::string& name, double ymin, double ymax) {
    require(data.is_array() && data.size() >= 2, name + " requires at least two [eV,value] points");
    Curve out;
    double last = 0;
    for (const auto& point : data) {
        require(point.is_array() && point.size() == 2 && point[0].is_number() && point[1].is_number(), name + ": malformed point");
        const double x = point[0].get<double>(), y = point[1].get<double>();
        require(std::isfinite(x) && x > last && x <= 100 && std::isfinite(y) && y >= ymin && y <= ymax,
                name + ": energies must be positive/strictly increasing and ordinates physically valid");
        out.emplace_back(x, y);
        last = x;
    }
    return out;
}
static Curve opticalProperty(const json& j, const char* name, double fallback, const Curve& emission, double lo, double hi) {
    if (!j.contains(name)) return {{emission.front().first, fallback}, {emission.back().first, fallback}};
    if (j.at(name).is_number()) {
        const double v = number(j, name, lo, hi);
        return {{emission.front().first, v}, {emission.back().first, v}};
    }
    return curve(j.at(name), name, lo, hi);
}
static void addCurve(G4MaterialPropertiesTable* mpt, const char* name, const Curve& c, double scale = 1.) {
    std::vector<G4double> e, v;
    for (const auto& point : c) { e.push_back(point.first * eV); v.push_back(point.second * scale); }
    mpt->AddProperty(name, e, v);
}
static void addQeCurve(G4MaterialPropertiesTable* table, const Curve& source) {
    // G4PhysicsVector uses endpoint values outside its range. Bound the complete
    // response independently of the scintillation band: Cherenkov light can span
    // the wider refractive-index domain.
    const double first = source.front().first * eV, last = source.back().first * eV;
    std::vector<G4double> energies{std::min(.001 * eV, first * .5), std::nextafter(first, 0.)};
    std::vector<G4double> values{0., 0.};
    for (const auto& point : source) { energies.push_back(point.first * eV); values.push_back(point.second); }
    // Apply nextafter after unit conversion, so the knots remain adjacent in the
    // exact internal energy representation used by G4OpBoundaryProcess.
    energies.push_back(std::nextafter(last, std::numeric_limits<double>::infinity())); values.push_back(0.);
    energies.push_back(std::max(1.e6 * eV, last * 2.)); values.push_back(0.);
    table->AddProperty("EFFICIENCY", energies, values);
}
static bool qeContains(const Curve& source, double photonEnergy) {
    return photonEnergy >= source.front().first * eV && photonEnergy <= source.back().first * eV;
}
static G4ThreeVector isotropic() {
    const double z = 2. * G4UniformRand() - 1.;
    const double phi = twopi * G4UniformRand();
    const double r = std::sqrt(std::max(0., 1. - z * z));
    return {r * std::cos(phi), r * std::sin(phi), z};
}
static json vectorJson(const G4ThreeVector& v, double unit = 1.) { return json::array({v.x() / unit, v.y() / unit, v.z() / unit}); }

#include "cathode_film.hpp"
#include "config_geometry.hpp"
#include "optical_boundary.hpp"

class Physics final : public G4VModularPhysicsList {
public:
    explicit Physics(const Configuration& config) {
        std::cerr << "[TwinPALS] Physics base constructed\n";
        SetVerboseLevel(0);
        std::cerr << "[TwinPALS] Creating decay physics\n";
        RegisterPhysics(new G4DecayPhysics(0));
        // Decay initialization resets shared EM defaults; install option4 afterwards.
        std::cerr << "[TwinPALS] Creating EM physics\n";
        RegisterPhysics(new G4EmStandardPhysics_option4(0));
        std::cerr << "[TwinPALS] Creating optical physics\n";
        RegisterPhysics(new G4OpticalPhysics(0));
        G4OpticalParameters::Instance()->SetProcessActivation("Cerenkov", config.includeCherenkov);
        G4OpticalParameters::Instance()->SetScintFiniteRiseTime(true);
        G4OpticalParameters::Instance()->SetVerboseLevel(0);
        defaultCutValue = 0.1 * mm;
    }
    void ConstructProcess() override {
        G4VModularPhysicsList::ConstructProcess();
        auto* manager = G4OpticalPhoton::Definition()->GetProcessManager();
        G4VProcess* original = nullptr;
        for (int i=0; i<manager->GetProcessListLength(); ++i)
            if (dynamic_cast<G4OpBoundaryProcess*>((*manager->GetProcessList())[i])) original = (*manager->GetProcessList())[i];
        require(original != nullptr, "Missing optical boundary process");
        manager->RemoveProcess(original);
        delete original;
        manager->AddDiscreteProcess(new OpticalBoundary());
    }
    void SetCuts() override { SetCutsWithDefault(); }
};


#include "transport.hpp"

class DiagnosticSession final : public G4UIsession {
public:
    G4int ReceiveG4cout(const G4String& message) override { std::lock_guard<std::mutex> lock(consoleMutex); std::cerr << message; return 0; }
    G4int ReceiveG4cerr(const G4String& message) override { std::lock_guard<std::mutex> lock(consoleMutex); std::cerr << message; return 0; }
};
class ExceptionHandler final : public G4VExceptionHandler {
public:
    G4bool Notify(const char* origin, const char* code, G4ExceptionSeverity severity, const char* description) override {
        const std::string message = std::string(origin) + " [" + code + "]: " + description;
        if (severity == JustWarning) { std::lock_guard<std::mutex> lock(consoleMutex); std::cerr << message << '\n'; return false; }
        throw std::runtime_error(message);
    }
};

class WorkerInitialization final : public G4UserWorkerInitialization {
public:
    void WorkerStart() const override {
        static thread_local DiagnosticSession diagnostic;
        static thread_local ExceptionHandler exceptions;
        G4UImanager::GetUIpointer()->SetCoutDestination(&diagnostic);
        G4StateManager::GetStateManager()->SetExceptionHandler(&exceptions);
    }
    void WorkerStop() const override {
        G4UImanager::GetUIpointer()->SetCoutDestination(nullptr);
        G4StateManager::GetStateManager()->SetExceptionHandler(nullptr);
    }
};

#include "worker_main.hpp"
