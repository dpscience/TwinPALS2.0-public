// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

class ActionInitialization final : public G4VUserActionInitialization {
    const Configuration& config; const Geometry& geometry; OrderedWriter& writer;
public:
    ActionInitialization(const Configuration& c, const Geometry& g, OrderedWriter& w) : config(c), geometry(g), writer(w) {}
    void Build() const override {
        auto state = std::make_shared<EventState>(); SetUserAction(new Generator(config, state)); SetUserAction(new Events(state, writer)); SetUserAction(new Tracking(config, geometry, state)); SetUserAction(new Stepping(config, geometry, state));
    }
};
int main(int argc, char** argv) {
    // Exceptions on Geant4 worker threads cannot reach main's catch block.
    // Publish the cause before terminating, instead of leaving only a Windows code.
    std::set_terminate([] {
        std::string message="Native worker terminated unexpectedly";
        try { if(auto error=std::current_exception())std::rethrow_exception(error); }
        catch(const std::exception& error){message=error.what();}
        catch(...){ }
        emitProtocol({{"type","error"},{"message",message}});
        std::_Exit(1);
    });
    try {
        if (argc==2 && std::string(argv[1])=="--self-test-boundary") {
            json probes=json::array(),edgeProbes=json::array();
            const double tolerance=G4GeometryTolerance::GetInstance()->GetSurfaceTolerance();
            for (double scale:{.001,1.,100.}) {
                std::vector<std::unique_ptr<G4VSolid>> solids;
                solids.emplace_back(new G4Cons("ConeProbe",0,9.5*scale,0,20*scale,13.95*scale,0,twopi));
                solids.emplace_back(new G4Tubs("CylinderProbe",0,14.75*scale,13.95*scale,0,twopi));
                solids.emplace_back(new G4Box("BoxProbe",14.75*scale,12*scale,13.95*scale));
                solids.emplace_back(new G4Trd("PyramidProbe",9.5*scale,20*scale,8*scale,16*scale,13.95*scale));
                for (const auto& solid:solids) {
                    const G4ThreeVector point(14.75*scale,0,0);
                    const auto normal=solid->SurfaceNormal(point);
                    const auto first=normal.orthogonal().unit(),second=normal.cross(first).unit();
                    for(const auto& direction:{first,second,(first+second).unit()}) {
                        G4ThreeVector corrected;
                        require(resolveGrazingReflection(*solid,point,direction,corrected),"Grazing probe did not run");
                        const auto chord=solid->DistanceToOut(point,corrected);
                        require(chord>16*tolerance,"Grazing reflection has no usable forward chord");
                        require((corrected-direction).mag()<.001,"Grazing correction exceeds its angular bound");
                        probes.push_back({{"solid",solid->GetEntityType()},{"scale",scale},{"angle_rad",(corrected-direction).mag()},{"chord_mm",chord/mm}});
                    }
                    G4ThreeVector unchanged;
                    require(!resolveGrazingReflection(*solid,point,-normal,unchanged),"Non-grazing reflection was altered");
                    require(!resolveGrazingReflection(*solid,point-1.e-3*scale*normal,first,unchanged),"Interior direction was altered");
                    const double edgeZ=13.95*scale-4*tolerance;
                    const bool tapered=solid->GetEntityType()=="G4Cons"||solid->GetEntityType()=="G4Trd";
                    const G4ThreeVector edge(14.75*scale+(tapered?edgeZ*10.5/27.9:0),0,edgeZ);
                    const auto edgeNormal=solid->SurfaceNormal(edge);
                    const G4ThreeVector trial(0,1,.1);
                    const auto exit=(trial-trial.dot(edgeNormal)*edgeNormal).unit();
                    require(solid->Inside(edge)==kSurface && exit.z()>0,"Invalid finite-edge probe");
                    require(!resolveGrazingReflection(*solid,edge,exit,unchanged),"Legitimate end-face exit was changed");
                    edgeProbes.push_back({{"solid",solid->GetEntityType()},{"scale",scale}});
                }
            }
            emitProtocol({{"type","boundary_self_test"},{"status","passed"},{"probes",probes},{"escaping_edge_probes",edgeProbes}});return 0;
        }
        if(argc==2 && std::string(argv[1])=="--self-test-lut") {
            G4OpticalSurface surface("LutProbabilityProbe",LUT,polishedteflonair,dielectric_LUT);
            CLHEP::MixMaxRng rng(19473);G4Random::setTheEngine(&rng);
            json probes=json::array();
            for(int incident:{0,45,89,90}) {
                const auto distribution=lutDistribution(surface,incident);const auto& bins=distribution.bins;
                const auto total=bins.back().cumulative;
                constexpr int draws=200000;std::vector<int> counts(bins.size());
                for(int n=0;n<draws;++n)++counts[&sampleLut(distribution,G4UniformRand())-bins.data()];
                double previous=0,maxZ=0;
                for(std::size_t i=0;i<bins.size();++i) {
                    const auto& bin=bins[i];const double probability=(bin.cumulative-previous)/total;
                    require(bin.theta>0&&bin.phi>0,"Exactly tangent LUT endpoint entered the inward distribution");
                    for(double rotation:{0.,.37,1.4}) {
                        G4ThreeVector normal(0,0,1),incoming(std::sin(incident*CLHEP::deg),0,-std::cos(incident*CLHEP::deg));
                        const G4ThreeVector axis(1,2,3);normal.rotate(rotation,axis);incoming.rotate(rotation,axis);
                        const auto direction=lutDirection(incoming,normal,incoming.angle(-normal),bin,
                            G4GeometryTolerance::GetInstance()->GetSurfaceTolerance());
                        const double expected=std::cos((-90+4*bin.theta)*CLHEP::deg)*std::cos((-90+5*bin.phi)*CLHEP::deg);
                        require(direction.dot(normal)>0 && std::abs(direction.dot(normal)-expected)<1.e-12,"LUT inward direction depends on detector rotation");
                    }
                    const auto& midpoint=sampleLut(distribution,(bin.cumulative+previous)/(2*total));
                    require(midpoint.theta==bin.theta&&midpoint.phi==bin.phi,"LUT cumulative interval maps to the wrong direction");
                    require(std::abs((bin.cumulative-previous)-surface.GetAngularDistributionValue(incident,bin.theta,bin.phi))<1.e-12,"LUT probability was changed");
                    const double sigma=std::sqrt(draws*probability*(1-probability));
                    maxZ=std::max(maxZ,std::abs(counts[i]-draws*probability)/sigma);previous=bin.cumulative;
                }
                require(maxZ<6,"Sampled LUT directions disagree with tabulated probabilities");
                probes.push_back({{"incident_deg",incident},{"draws",draws},{"bins",bins.size()},{"max_standardized_residual",maxZ}});
            }
            // Include exactly representable edges and their immediate neighbors
            // for every incident angle, including the degenerate last bucket.
            for(int incident=0;incident<=90;++incident){
                const auto distribution=lutDistribution(surface,incident);
                const auto& bins=distribution.bins;
                const auto check=[&](double u){
                    const auto it=std::upper_bound(bins.begin(),bins.end(),u*bins.back().cumulative,
                        [](double x,const LutAngle& b){return x<b.cumulative;});
                    require(&sampleLut(distribution,u)==&(it==bins.end()?bins.back():*it),"Indexed LUT differs from reference search");
                };
                for(const auto& bin:bins){
                    const double u=bin.cumulative/bins.back().cumulative;
                    check(u);check(std::nextafter(u,0.));check(std::nextafter(u,1.));
                }
                for(size_t i=0;i<=LutDistribution::slices;++i){
                    const double u=static_cast<double>(i)/LutDistribution::slices;
                    check(u);check(std::nextafter(u,0.));check(std::nextafter(u,1.));
                }
            }
            emitProtocol({{"type","lut_self_test"},{"status","passed"},{"probes",probes}});return 0;
        }
        if (argc == 2 && std::string(argv[1]) == "--materials") {
            auto* nist = G4NistManager::Instance(); json materials = json::array();
            for (const auto& name : nist->GetNistMaterialNames()) {
                auto* material = nist->FindOrBuildMaterial(name, true, false);
                require(material != nullptr, "Cannot construct standard material: " + std::string(name));
                json composition = json::object();
                const auto* elements = material->GetElementVector();
                const auto* fractions = material->GetFractionVector();
                const auto* atoms = material->GetAtomsVector();
                json atomic = json::object();
                for (std::size_t i = 0; i < material->GetNumberOfElements(); ++i)
                    composition[std::string((*elements)[i]->GetSymbol())] = fractions[i];
                if (atoms) for (std::size_t i = 0; i < material->GetNumberOfElements(); ++i)
                    atomic[std::string((*elements)[i]->GetSymbol())] = atoms[i];
                // Geant4 also exposes rounded atom counts for mass mixtures. Only
                // retain counts that reproduce the actual mass fractions.
                double atomicMass = 0.;
                if (atoms) for (std::size_t i = 0; i < material->GetNumberOfElements(); ++i)
                    atomicMass += atoms[i] * (*elements)[i]->GetA();
                if (atoms) for (std::size_t i = 0; i < material->GetNumberOfElements(); ++i)
                    if (atoms[i] <= 0 || atomicMass <= 0. || std::abs(atoms[i]*(*elements)[i]->GetA()/atomicMass-fractions[i]) > 1.e-8) { atomic = json::object(); break; }
                materials.push_back({{"id", std::string(name)}, {"density_g_cm3", material->GetDensity() / (g/cm3)},
                    {"composition", composition}, {"composition_basis", "mass_fraction"},
                    {"atomic_composition", atomic}, {"chemical_formula", std::string(material->GetChemicalFormula())},
                    {"state", material->GetState() == kStateGas ? "gas" : material->GetState() == kStateLiquid ? "liquid" : "solid"}});
            }
            emitProtocol({{"format", "twinpals-geant4-materials"}, {"geant4_version", kEngineVersion}, {"items", materials}}); return 0;
        }
        if (argc == 2 && std::string(argv[1]) == "--self-test-qe") {
            const Curve original{{2.5, .4}, {3.5, .8}, {4.5, .2}};
            G4MaterialPropertiesTable table; addQeCurve(&table, original);
            const auto* values = table.GetProperty("EFFICIENCY"); json probes = json::array();
            for (double energy : {.001, .1, 1., 2.49, 2.5, 3.5, 4.5, 4.51, 8., 100., 1.e6, 2.e6}) {
                const double probability = values->Value(energy * eV);
                require(qeContains(original, energy * eV) || probability == 0., "QE extrapolation outside original table is not zero");
                probes.push_back({{"energy_eV", energy}, {"qe", probability}});
            }
            for (const auto& knot : original) require(std::abs(values->Value(knot.first * eV) - knot.second) < 1.e-12, "Original QE knot was changed");
            require(!qeContains(original, std::nextafter(2.5 * eV, 0.)) && !qeContains(original, std::nextafter(4.5 * eV, std::numeric_limits<double>::infinity())), "QE cutoff guard failed");
            require(values->Value(std::nextafter(2.5 * eV, 0.)) == 0. && values->Value(std::nextafter(4.5 * eV, std::numeric_limits<double>::infinity())) == 0., "Adjacent outside-band energies must have zero QE");
            emitProtocol({{"type", "qe_self_test"}, {"status", "passed"}, {"probes", probes}, {"original_knots_preserved", true}, {"outside_domain_exact_guard", true}}); return 0;
        }
        if (argc == 2 && std::string(argv[1]) == "--version") {
            emitProtocol({{"engine", "Geant4"}, {"version", kEngineVersion}, {"worker_version", kWorkerVersion}, {"stream_version", 6}, {"geant4_build", G4Version}, {"multithreaded", true}, {"max_threads", 256}, {"cpu_count", std::max(1u, std::thread::hardware_concurrency())}, {"rng_policy", kRngPolicy}}); return 0;
        }
        std::string configFile, outputDirectory; bool validateOnly = false;
        for (int i = 1; i < argc; ++i) { const std::string arg = argv[i]; if (arg == "--validate") { validateOnly = true; continue; } require((arg == "--config" || arg == "--output") && i + 1 < argc, "Usage: twinpals-worker --config input.json --output directory"); (arg == "--config" ? configFile : outputDirectory) = argv[++i]; }
        require(!configFile.empty() && !outputDirectory.empty(), "Both --config and --output are required");
        std::ifstream input(fs::u8path(configFile)); require(input.good(), "Cannot open native configuration"); Configuration config(json::parse(input));
        fs::create_directories(fs::u8path(outputDirectory));
        DiagnosticSession diagnostic; ExceptionHandler exceptions;
        G4StateManager::GetStateManager()->SetExceptionHandler(&exceptions); G4UImanager::GetUIpointer()->SetCoutDestination(&diagnostic);
        CLHEP::MixMaxRng randomEngine; G4Random::setTheEngine(&randomEngine); G4Random::setTheSeed(config.seed);
        if (validateOnly) {
            Geometry geometry(config); geometry.Construct(); geometry.validateOverlaps();
            G4UImanager::GetUIpointer()->SetCoutDestination(nullptr); G4StateManager::GetStateManager()->SetExceptionHandler(nullptr);
            emitProtocol({{"type", "validation"}, {"valid", true}, {"overlap_check_samples", 2000}}); return 0;
        }
        OrderedWriter writer(config, fs::u8path(outputDirectory));
        auto run = std::make_unique<G4MTRunManager>(); run->SetNumberOfThreads(config.threads);
        require(run->GetNumberOfThreads() == config.threads, "G4FORCENUMBEROFTHREADS conflicts with requested threads");
        run->SetEventModulo(1); G4MTRunManager::SetSeedOncePerCommunication(0);
        auto* geometry = new Geometry(config); run->SetUserInitialization(geometry); run->SetUserInitialization(new Physics(config));
        run->SetUserInitialization(new ActionInitialization(config, *geometry, writer)); run->SetUserInitialization(new WorkerInitialization()); run->SetPrintProgress(0);
        run->Initialize(); geometry->validateOverlaps(); G4Random::setTheSeed(config.seed);
        json electronProcesses = json::array();
        const auto* electronManager = G4Electron::Definition()->GetProcessManager();
        if (electronManager) for (int i = 0; i < electronManager->GetProcessListLength(); ++i) electronProcesses.push_back((*electronManager->GetProcessList())[i]->GetProcessName());
        emitProtocol({{"type", "physics_processes"}, {"electron_processes", electronProcesses}, {"cerenkov_configured", G4OpticalParameters::Instance()->GetProcessActivation("Cerenkov")}, {"finite_rise_time", G4OpticalParameters::Instance()->GetScintFiniteRiseTime()}, {"minimum_energy_keV", config.minimumEnergyKeV}});
        emitProtocol({{"type", "started"}, {"engine", "Geant4"}, {"version", kEngineVersion}, {"worker_version", kWorkerVersion}, {"threads", config.threads}, {"multithreaded", true}, {"source_role", config.sourceRole}, {"rng", "CLHEP::MixMaxRng"}, {"rng_policy", kRngPolicy}, {"seed", config.seed}, {"seed_once_per_communication", 0}, {"event_modulo", 1}, {"normalization", "selected_gamma_ensemble"}, {"reorder_pending_bytes_limit", kReorderBytesLimit}, {"reorder_pending_events_limit", reorderEventLimit(config.threads)}, {"physics", "G4EmStandardPhysics_option4+G4DecayPhysics+G4OpticalPhysics"}, {"production_cut_mm", .1}, {"overlap_check_samples", 2000}});
        emitProtocol({{"type", "progress"}, {"completed", 0}, {"total", config.events}}); run->BeamOn(config.events);
        const auto completion = writer.finish(); run.reset(); G4UImanager::GetUIpointer()->SetCoutDestination(nullptr); G4StateManager::GetStateManager()->SetExceptionHandler(nullptr); emitProtocol(completion); return 0;
    } catch (const std::exception& e) { std::cerr << "TwinPALS native failure: " << e.what() << '\n'; emitProtocol({{"type", "error"}, {"message", e.what()}}); return 1; }
}
