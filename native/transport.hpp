// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

// Provenance is bookkeeping only: no extra random draw or transport decision.
static json lightComponents(const Configuration& c) {
    json result=json::array({{{"id",0},{"volume","World"},{"label","Surrounding air"},{"material","Air"}}});
    auto add=[&](std::string volume,std::string label,const json& material){result.push_back({{"id",result.size()},{"volume",volume},{"label",label},{"material",material.value("name",material.value("id",material.value("nist_material",std::string("Vacuum"))))}});};
    for(int d=0;d<2;++d){const auto& x=c.detectors[d];const std::string id=d?"B":"A";
        add("Scint"+id,"Crystal "+id,x.material);add("Coupling"+id,"Coupling "+id,x.coupling);add("Window"+id,"PMT window "+id,x.window);
        add("PMTEnvelope"+id,"PMT vacuum "+id,json::object());add("Cathode"+id,"Cathode "+id,json{{"name","Aluminium"}});
        add("Wrap"+id,"Wrapping "+id,x.surface.value("material",json::object()));add("WrapFront"+id,"Front wrapping "+id,x.surface.value("material",json::object()));}
    for(const auto& item:std::array<std::pair<std::string,json>,2>{{{"Sample",c.samples},{"Shield",c.shields}}})for(std::size_t i=0;i<item.second.size();++i){const auto& b=item.second[i];const auto id=b.value("id",std::to_string(i));add(item.first+"_"+id,item.first+" "+id,b.at("material"));}
    require(result.size()<256,"Too many light-origin components");return result;
}
struct HistoryNode {
    uint32_t parent=0,track=0,parentTrack=0,primary=0,component=0,nextComponent=0;
    int pdg=0; std::string process;
    double time=0,energyBefore=0,energyAfter=0;
    G4ThreeVector position,directionBefore,directionAfter;
};
struct LightOrigin { uint8_t mechanism=0,component=0; uint32_t history=0; G4ThreeVector birth; };
struct TrackRecord { int primary=-1; LightOrigin light; };
struct DetectorSummary {
    double energy = 0, arrivalSum = 0, trackLengthSum = 0;
    uint64_t detected = 0, reflections = 0;
    uint32_t reentries = 0;
    bool hasInteraction = false;
    bool entered = false;
    double interactionTime = 0;
    G4ThreeVector interaction;
    std::vector<double> arrivals;
    std::vector<std::array<float,2>> positions;
    std::vector<std::array<uint8_t,2>> origins;
    std::vector<uint32_t> history;
    json cherenkovBirths=json::array();
    unsigned originMask=0, productionMask=0;
    void detect(double t, double length, const G4ThreeVector& local) { ++detected; arrivalSum += t; trackLengthSum += length; arrivals.push_back(t); positions.push_back({static_cast<float>(local.x()/mm),static_cast<float>(local.y()/mm)}); }
    void interact(const G4ThreeVector& p, double t) { if (!hasInteraction || t < interactionTime) { hasInteraction = true; interaction = p; interactionTime = t; } }
    void add(const DetectorSummary& p) {
        energy += p.energy; arrivalSum += p.arrivalSum; trackLengthSum += p.trackLengthSum;
        detected += p.detected; reflections += p.reflections; reentries += p.reentries;
        arrivals.insert(arrivals.end(),p.arrivals.begin(),p.arrivals.end());
        positions.insert(positions.end(),p.positions.begin(),p.positions.end());
        origins.insert(origins.end(),p.origins.begin(),p.origins.end());originMask|=p.originMask;productionMask|=p.productionMask;
        history.insert(history.end(),p.history.begin(),p.history.end());
        for(const auto& birth:p.cherenkovBirths)if(cherenkovBirths.size()<64)cherenkovBirths.push_back(birth);
        entered = entered || p.entered;
        if (p.hasInteraction) interact(p.interaction, p.interactionTime);
    }
};
struct PrimaryState {
    int slot = 0;
    double gammaEnergy = 0, emissionTime = 0;
    G4ThreeVector direction;
    std::array<DetectorSummary, 2> detectors;
};
struct PreviewTrack {
    std::string particle,detector;
    int primary=0,track=0,parent=0;
    std::vector<G4ThreeVector> points;
    json encode() const {
        json vertices=json::array();for(const auto& p:points)vertices.push_back(vectorJson(p,mm));
        return {{"particle",particle},{"detector",detector},{"primary_id",primary},{"track_id",track},{"parent_id",parent},{"points_mm",std::move(vertices)}};
    }
};
struct EventState {
    int id = 0;
    G4ThreeVector sourcePosition;
    std::vector<PrimaryState> primaries;
    // Geant4 assigns contiguous track IDs within an event. Keep parent records
    // through suspensions and secondary tracking, independently of the preview.
    std::vector<TrackRecord> trackRecords;
    PreviewTrack* activePreview=nullptr;
    int activePrimary=-1;
    std::unordered_map<int, uint8_t> exitedCrystals;
    // Immutable shared prefixes, one-based IDs; zero means no preceding node.
    std::vector<HistoryNode> history;
    std::unordered_map<int,uint32_t> historyHeads;
    std::unordered_map<const G4Track*,uint32_t> birthHistory;
    std::map<int, PreviewTrack> tracks;
    std::array<std::array<int,2>,3> opticalPreview{};
    int nonOpticalPreview = 0;
    bool sampleTrajectory = false;
    std::chrono::steady_clock::time_point started;
    // Opt-in research diagnostics; no additional stream payload or RNG draws.
    bool auditLight = false;
    std::unordered_map<int,std::string> opticalOrigins;
    std::array<std::map<std::string,uint64_t>,2> acceptedOrigins;
};
class PrimaryTag final : public G4VUserPrimaryParticleInformation {
public:
    int index;
    explicit PrimaryTag(int i) : index(i) {}
    void Print() const override {}
};
class Generator final : public G4VUserPrimaryGeneratorAction {
    const Configuration& c; std::shared_ptr<EventState> owner; EventState& state;
    void emit(G4Event* event, int slot, double energy, double time, const G4ThreeVector& direction) {
        const int index = static_cast<int>(state.primaries.size());
        PrimaryState p; p.slot = slot; p.gammaEnergy = energy; p.emissionTime = time; p.direction = direction; state.primaries.push_back(p);
        auto* vertex = new G4PrimaryVertex(state.sourcePosition, time * ns);
        auto* gamma = new G4PrimaryParticle(G4Gamma::Definition()); gamma->SetKineticEnergy(energy * keV);
        gamma->SetMomentumDirection(direction); gamma->SetUserInformation(new PrimaryTag(index)); vertex->SetPrimary(gamma); event->AddPrimaryVertex(vertex);
    }
public:
    Generator(const Configuration& cfg, std::shared_ptr<EventState> event) : c(cfg), owner(std::move(event)), state(*owner) {}
    void GeneratePrimaries(G4Event* event) override {
        auto records=std::move(state.trackRecords);
        records.clear();
        state = EventState{}; state.id = event->GetEventID();
        // Bound idle worker memory after an exceptionally bright event.
        if(records.capacity()<=65536)state.trackRecords=std::move(records);
        state.started=std::chrono::steady_clock::now();
        static const bool auditLight = std::getenv("TWINPALS_AUDIT_LIGHT") != nullptr;
        state.auditLight = auditLight;
        // Capture bounded tracks independently of event outcome; publication is throttled.
        state.sampleTrajectory = c.trajectoryLimit > 0;
        const double r = c.sourceRadius * std::sqrt(G4UniformRand()), phi = twopi * G4UniformRand();
        const G4ThreeVector p(r * std::cos(phi) * mm, r * std::sin(phi) * mm, c.sourceThickness * (G4UniformRand() - .5) * mm);
        state.sourcePosition = c.sourcePosition + c.sourceRotation * p;
        if (c.sourceRole == "na22_prompt") emit(event, 0, 1274.537, 0., isotropic());
        else if (c.sourceRole == "na22_annihilation") { const auto direction = isotropic(); emit(event, 1, 511., 0., direction); emit(event, 2, 511., 0., -direction); }
        else {
            const auto first = isotropic(); double mu;
            // E2-E2 main cascade: normalized conditional p(mu)=10/21*(1+mu^2/8+mu^4/24).
            do { mu = 2. * G4UniformRand() - 1.; } while (G4UniformRand() * (7. / 6.) > 1. + mu * mu / 8. + std::pow(mu, 4) / 24.);
            const double azimuth = twopi * G4UniformRand(); const auto u = first.orthogonal().unit(), v = first.cross(u).unit();
            const auto second = mu * first + std::sqrt(std::max(0., 1. - mu * mu)) * (std::cos(azimuth) * u + std::sin(azimuth) * v);
            emit(event, 0, 1173.228, 0., first); emit(event, 1, 1332.492, 0., second);
        }
    }
};
class Tracking final : public G4UserTrackingAction {
    const Configuration& c; const Geometry& geometry;
    std::shared_ptr<EventState> owner; EventState& state;
    std::map<std::string,uint8_t> componentIds;
public:
    Tracking(const Configuration& cfg, const Geometry& g, std::shared_ptr<EventState> event) : c(cfg), geometry(g), owner(std::move(event)), state(*owner) {for(const auto& x:lightComponents(c))componentIds[x.at("volume").get<std::string>()]=x.at("id").get<uint8_t>();}
    void PreUserTrackingAction(const G4Track* track) override try {
        const int id=track->GetTrackID(), parent=track->GetParentID();
        require(id>0 && parent>=0,"Invalid track ancestry ID");
        int primary = -1;
        if (parent == 0) {
            const auto* particle = track->GetDynamicParticle()->GetPrimaryParticle();
            const auto* tag = particle ? dynamic_cast<const PrimaryTag*>(particle->GetUserInformation()) : nullptr; if (tag) primary = tag->index;
        } else if(static_cast<size_t>(parent)<state.trackRecords.size())primary=state.trackRecords[parent].primary;
        require(primary >= 0 && primary < static_cast<int>(state.primaries.size()), "Lost primary ancestry");
        if(static_cast<size_t>(id)>=state.trackRecords.size())state.trackRecords.resize(static_cast<size_t>(id)+1);
        auto& record=state.trackRecords[id];
        const bool resumed=record.primary>=0;
        state.activePrimary=record.primary=primary;
        state.activePreview=nullptr;
        const bool optical = track->GetDefinition() == G4OpticalPhoton::Definition();
        // Suspended tracks may be resumed; do not recreate their birth record.
        if(resumed){
            const auto it=state.tracks.find(id);
            if(it!=state.tracks.end())state.activePreview=&it->second;
            return;
        }
        uint32_t birth=0;
        auto saved=state.birthHistory.find(track);
        if(saved!=state.birthHistory.end()){birth=saved->second;state.birthHistory.erase(saved);}
        if(!optical){
            HistoryNode node;node.parent=birth;node.track=track->GetTrackID();node.parentTrack=track->GetParentID();node.primary=state.primaries[primary].slot;
            node.component=node.nextComponent=componentIds.at(track->GetVolume()->GetName());node.pdg=track->GetDefinition()->GetPDGEncoding();
            node.process=track->GetCreatorProcess()?std::string(track->GetCreatorProcess()->GetProcessName()):"Primary";
            node.time=track->GetGlobalTime()/ns;node.position=track->GetPosition()/mm;node.energyBefore=node.energyAfter=track->GetKineticEnergy()/keV;
            node.directionBefore=node.directionAfter=track->GetMomentumDirection();state.history.push_back(node);state.historyHeads[track->GetTrackID()]=static_cast<uint32_t>(state.history.size());
        }
        if(optical){const auto* creator=track->GetCreatorProcess();const std::string_view process=creator?std::string_view(creator->GetProcessName()):std::string_view();
            LightOrigin origin;origin.mechanism=process=="Scintillation"?1:process=="Cerenkov"?2:0;
            if(!origin.mechanism){
                const auto& inherited=state.trackRecords[parent].light;
                require(inherited.mechanism!=0,"Unknown optical production mechanism");
                origin=inherited;
            } else {
                origin.component=componentIds.at(track->GetVolume()->GetName());
                origin.birth=track->GetPosition();
                origin.history=birth;
                if(!birth)throw std::runtime_error("Missing light-production ancestry: event "+std::to_string(state.id)+", track "+std::to_string(id)+", parent "+std::to_string(parent)+", step "+std::to_string(track->GetCurrentStepNumber())+", process "+std::string(process)+", parent optical "+std::to_string(state.trackRecords[parent].light.mechanism!=0)+", parent history "+std::to_string(state.historyHeads.count(parent)));
                const int createdIn=track->GetVolume()==geometry.detectors[0]?0:track->GetVolume()==geometry.detectors[1]?1:-1;
                if(createdIn>=0)state.primaries[primary].detectors[createdIn].productionMask|=origin.mechanism;
            }
            record.light=origin;
        }
        if(state.auditLight && optical) {
            const auto* creator=track->GetCreatorProcess();
            state.opticalOrigins[track->GetTrackID()]=(creator?std::string(creator->GetProcessName()):"primary")+std::string(" @ ")+(track->GetVolume()?std::string(track->GetVolume()->GetName()):"outside");
        }
        const int detector = track->GetVolume()==geometry.detectors[0]?0:track->GetVolume()==geometry.detectors[1]?1:-1;
        // Each output stream and detector gets its own optical budget. This
        // prevents the first crystal from consuming every displayed trajectory.
        const int group = c.sourceRole=="co60"?primary:0;
        if (state.sampleTrajectory && (optical
                ? detector>=0 && state.opticalPreview[group][detector]<c.opticalTracksPerDetector
                : state.nonOpticalPreview<128)) {
            auto& preview=state.tracks[id];
            preview = {track->GetDefinition()->GetParticleName(),detector>=0?(detector==0?"A":"B"):"",
                state.primaries[primary].slot,track->GetTrackID(),track->GetParentID(),{track->GetPosition()}};
            state.activePreview=&preview;
            if (optical) ++state.opticalPreview[group][detector]; else ++state.nonOpticalPreview;
        }
    } catch(const std::exception& e) {emitProtocol({{"type","error"},{"message",std::string("Track ancestry: ")+e.what()}});std::_Exit(1);}
};
class Stepping final : public G4UserSteppingAction {
    const Geometry& geometry; std::shared_ptr<EventState> owner; EventState& state; G4OpBoundaryProcess* boundary = nullptr;
    std::map<std::string,uint32_t> componentIds;
public:
    Stepping(const Configuration& c,const Geometry& g, std::shared_ptr<EventState> event) : geometry(g), owner(std::move(event)), state(*owner) {for(const auto& x:lightComponents(c))componentIds[x.at("volume").get<std::string>()]=x.at("id").get<uint32_t>();}
    void UserSteppingAction(const G4Step* step) override try {
        const auto* track = step->GetTrack(); const int primary = state.activePrimary; auto& response = state.primaries[primary].detectors;
        auto* pre = step->GetPreStepPoint()->GetPhysicalVolume(); auto* post = step->GetPostStepPoint()->GetPhysicalVolume();
        const bool optical = track->GetDefinition() == G4OpticalPhoton::Definition();
        const bool gamma = track->GetDefinition() == G4Gamma::Definition();
        // Optical absorption can itself create scintillation descendants. Keep
        // that relay node only when it branches, not every optical transport step.
        if(optical && step->GetSecondary() && step->GetNumberOfSecondariesInCurrentStep()!=0) {
            const auto* before=step->GetPreStepPoint();const auto* after=step->GetPostStepPoint();
            HistoryNode node;node.parent=state.trackRecords[track->GetTrackID()].light.history;
            node.track=track->GetTrackID();node.parentTrack=track->GetParentID();node.primary=state.primaries[primary].slot;
            node.component=componentIds.at(pre->GetName());node.nextComponent=post?componentIds.at(post->GetName()):0;
            node.pdg=track->GetDefinition()->GetPDGEncoding();node.process=after->GetProcessDefinedStep()?std::string(after->GetProcessDefinedStep()->GetProcessName()):"Optical relay";
            node.time=after->GetGlobalTime()/ns;node.position=after->GetPosition()/mm;
            node.energyBefore=before->GetKineticEnergy()/keV;node.energyAfter=after->GetKineticEnergy()/keV;
            node.directionBefore=before->GetMomentumDirection();node.directionAfter=after->GetMomentumDirection();state.history.push_back(node);
            for(const auto* secondary:*step->GetSecondaryInCurrentStep())state.birthHistory[secondary]=static_cast<uint32_t>(state.history.size());
        }
        if (!optical) {
            const auto* before=step->GetPreStepPoint();const auto* after=step->GetPostStepPoint();
            const auto* process=after->GetProcessDefinedStep();
            HistoryNode node;node.parent=state.historyHeads.at(track->GetTrackID());node.track=track->GetTrackID();node.parentTrack=track->GetParentID();node.primary=state.primaries[primary].slot;
            node.component=componentIds.at(pre->GetName());node.nextComponent=post?componentIds.at(post->GetName()):0;
            node.pdg=track->GetDefinition()->GetPDGEncoding();node.process=process?std::string(process->GetProcessName()):"Step";
            node.time=after->GetGlobalTime()/ns;node.position=after->GetPosition()/mm;node.energyBefore=before->GetKineticEnergy()/keV;node.energyAfter=after->GetKineticEnergy()/keV;
            node.directionBefore=before->GetMomentumDirection();node.directionAfter=after->GetMomentumDirection();state.history.push_back(node);
            const auto head=static_cast<uint32_t>(state.history.size());state.historyHeads[track->GetTrackID()]=head;
            // Capture NOW: tracking a secondary can occur after the parent has
            // moved again. Looking up its parent's final head would be incorrect.
            for(const auto* secondary:*step->GetSecondaryInCurrentStep())state.birthHistory[secondary]=head;
            for (int d = 0; d < 2; ++d) {
                if (pre == geometry.detectors[d] || post == geometry.detectors[d]) response[d].entered = true;
                if (pre == geometry.detectors[d]) {
                    response[d].energy += step->GetTotalEnergyDeposit() / keV;
                    const auto* process = step->GetPostStepPoint()->GetProcessDefinedStep();
                    if (gamma && process && process->GetProcessName() != "Transportation" && process->GetProcessName() != "CoupledTransportation")
                        response[d].interact(step->GetPostStepPoint()->GetPosition(), step->GetPostStepPoint()->GetGlobalTime() / ns);
                    if (gamma && post != pre) state.exitedCrystals[track->GetTrackID()] |= static_cast<uint8_t>(1 << d);
                } else if (gamma && post == geometry.detectors[d] && (state.exitedCrystals[track->GetTrackID()] & (1 << d))) ++response[d].reentries;
            }
        } else if (step->GetPostStepPoint()->GetStepStatus() == fGeomBoundary) {
            // The inactive window edge ends at the opaque tube surround. Model
            // its optical absorption without adding an invented wall material.
            // In the external-QE convention bulk loss is already included in QE;
            // an ideally lossless, polished, uncovered rim would trap skew rays.
            for (int d=0;d<2;++d) if(pre==geometry.windows[d]) {
                const auto local=step->GetPreStepPoint()->GetTouchableHandle()->GetHistory()->GetTopTransform().TransformPoint(step->GetPostStepPoint()->GetPosition());
                const auto normal=pre->GetLogicalVolume()->GetSolid()->SurfaceNormal(local);
                if(std::abs(normal.z())<.5) { step->GetTrack()->SetTrackStatus(fStopAndKill); return; }
            }
            if (!boundary) { auto* processes = G4OpticalPhoton::Definition()->GetProcessManager()->GetProcessList(); for (std::size_t i = 0; i < processes->size(); ++i) if (auto* p = dynamic_cast<G4OpBoundaryProcess*>((*processes)[i])) { boundary = p; break; } require(boundary != nullptr, "Missing optical boundary process"); }
            const auto status = boundary->GetStatus();
            if (reflectionStatus(status)) for (int d = 0; d < 2; ++d) if (pre == geometry.detectors[d] || pre == geometry.windows[d]) ++response[d].reflections;
            if (status == Detection) {
                const int d = post == geometry.sensors[0] ? 0 : post == geometry.sensors[1] ? 1 : -1;
                require(d >= 0, "Detection outside configured cathode");
                // Endpoint interpolation/scaling can round a cutoff knot by one
                // representable energy. The original table domain is authoritative.
                // Outside-band photons are still absorbed; they cannot make a PE.
                if (geometry.acceptsQeEnergy(d, step->GetPreStepPoint()->GetKineticEnergy())) {
                    const auto local=step->GetPostStepPoint()->GetTouchableHandle()->GetHistory()->GetTopTransform().TransformPoint(step->GetPostStepPoint()->GetPosition());
                    response[d].detect(step->GetPostStepPoint()->GetGlobalTime() / ns, track->GetTrackLength() / mm,local);
                    const auto& origin=state.trackRecords[track->GetTrackID()].light;response[d].origins.push_back({origin.mechanism,origin.component});response[d].originMask|=origin.mechanism;
                    response[d].history.push_back(origin.history);
                    if(state.sampleTrajectory && origin.mechanism==2 && response[d].cherenkovBirths.size()<64)response[d].cherenkovBirths.push_back({{"component",origin.component},{"position_mm",vectorJson(origin.birth,mm)}});
                    if(state.auditLight) ++state.acceptedOrigins[d][state.opticalOrigins.at(track->GetTrackID())];
                }
            }
        }
        if (state.activePreview && state.activePreview->points.size()<256)
            state.activePreview->points.push_back(step->GetPostStepPoint()->GetPosition());
    } catch(const std::exception& e) {emitProtocol({{"type","error"},{"message",std::string("Step ancestry: ")+e.what()}});std::_Exit(1);}
};

#include "stream_crc.hpp"
static uint32_t crc32(const std::string& bytes) {return stream_crc::calculate(reinterpret_cast<const unsigned char*>(bytes.data()),bytes.size());}
static void appendU32(std::string& out, uint32_t v) {
#if defined(_WIN32) || (defined(__BYTE_ORDER__) && __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__)
    out.append(reinterpret_cast<const char*>(&v),sizeof(v));
#else
    for(int i=0;i<4;++i)out.push_back(static_cast<char>((v>>(8*i))&255));
#endif
}
static void appendU64(std::string& out, uint64_t v) {
#if defined(_WIN32) || (defined(__BYTE_ORDER__) && __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__)
    out.append(reinterpret_cast<const char*>(&v),sizeof(v));
#else
    for(int i=0;i<8;++i)out.push_back(static_cast<char>((v>>(8*i))&255));
#endif
}
static void appendDouble(std::string& out, double v) { require(std::isfinite(v), "Nonfinite stream double"); uint64_t bits; static_assert(sizeof(bits) == sizeof(v)); std::memcpy(&bits, &v, sizeof(v)); appendU64(out, bits); }
static void appendFloat(std::string& out,float v) {require(std::isfinite(v),"Nonfinite hit coordinate");uint32_t bits;std::memcpy(&bits,&v,sizeof(v));appendU32(out,bits);}
static void appendVector(std::string& out, const G4ThreeVector& v, double unit = 1.) { appendDouble(out, v.x() / unit); appendDouble(out, v.y() / unit); appendDouble(out, v.z() / unit); }
static void frame(std::ofstream& f, const char* tag, const std::string& payload,uint32_t checksum) {
    require(payload.size() <= 16 * 1024 * 1024, "Frame exceeds 16 MiB"); std::string prefix(tag, 4); appendU32(prefix, static_cast<uint32_t>(payload.size())); appendU32(prefix, checksum);
    f.write(prefix.data(), static_cast<std::streamsize>(prefix.size())); f.write(payload.data(), static_cast<std::streamsize>(payload.size())); require(f.good(), "Cannot write stream frame");
}
static void frame(std::ofstream& f,const char* tag,const std::string& payload){frame(f,tag,payload,crc32(payload));}
struct AnalogEvent {
    std::string event,pulse,provenance;std::array<std::string,2> hits;
    std::array<std::vector<double>,2> preview,arrivals;
    std::array<std::vector<std::array<uint8_t,2>>,2> origins;
    json births=json::array();
};
static AnalogEvent eventBytes(const EventState& state, int projection,const Configuration& c) {
    AnalogEvent result;auto& out=result.event;out.reserve(324);appendU64(out,state.id);
    uint32_t mask = 0; std::array<G4ThreeVector, 3> dirs{}; std::array<double, 3> times{};
    for (const auto& p : state.primaries) { mask |= 1u << p.slot; dirs[p.slot] = p.direction; times[p.slot] = p.emissionTime; }
    appendU32(out, mask); appendVector(out, state.sourcePosition, mm); for (const auto& d : dirs) appendVector(out, d); for (double t : times) appendDouble(out, t);
    const double emission = projection >= 0 ? state.primaries[projection].emissionTime : state.primaries.front().emissionTime;
    appendU64(result.pulse,state.id);
    std::array<std::vector<double>,2> raw,onsets;
    std::array<std::vector<std::array<float,2>>,2> positions;
    std::array<std::vector<std::array<uint8_t,2>>,2> origins;
    std::array<std::vector<uint32_t>,2> historyRefs;
    for (int d = 0; d < 2; ++d) {
        DetectorSummary s; for (std::size_t p = 0; p < state.primaries.size(); ++p) if (projection < 0 || projection == static_cast<int>(p)) s.add(state.primaries[p].detectors[d]);
        appendU32(out, (s.detected ? 1u : 0u) | (s.hasInteraction ? 2u : 0u) | (s.energy >= c.minimumEnergyKeV ? 4u : 0u) | (s.entered ? 8u : 0u) | (s.originMask<<4)|(s.productionMask<<6)); appendU64(out, s.detected); appendDouble(out, s.energy);
        appendDouble(out, s.detected ? s.arrivalSum / s.detected - emission : 0); appendVector(out, s.interaction, mm);
        appendDouble(out, s.hasInteraction ? s.interactionTime - emission : 0); appendDouble(out, s.detected ? s.trackLengthSum / s.detected : 0); appendU64(out, s.reflections); appendU32(out, s.reentries);
        const auto& p=c.document.at("analog_response").at(d);
        analog_pmt::Response response;
        response.order=p.at("order").get<int>();response.tau=p.at("tau_ns").get<double>();
        response.delay=p.at("onset_delay_ns").get<double>();response.sigma=p.at("tts_sigma_ns").get<double>();
        response.voltageScale=p.at("voltage_scale_mV").get<double>();response.polarity=p.at("polarity")=="negative"?-1:1;
        require(response.order>=2&&response.order<=32&&response.tau>0&&response.sigma>=0,"Invalid analog response");
        raw[d]=std::move(s.arrivals);for(double& t:raw[d])t-=emission;
        positions[d]=std::move(s.positions);
        origins[d]=std::move(s.origins);result.births.push_back(s.cherenkovBirths);
        historyRefs[d]=std::move(s.history);
        const uint64_t analogSeed=static_cast<uint64_t>(c.seed) ^ (static_cast<uint64_t>(state.id)+1)*0xd1b54a32d192ed03ULL ^ (static_cast<uint64_t>(projection+2)*2+d)*0x94d049bb133111ebULL;
        onsets[d]=analog_pmt::onsets(raw[d],response,analogSeed);
        const double amplitude=analog_pmt::peak(onsets[d],response);
        appendDouble(out,response.polarity<0?-amplitude:0);appendDouble(out,response.polarity>0?amplitude:0);
        appendU32(result.pulse,static_cast<uint32_t>(raw[d].size()));
    }
    for(int d=0;d<2;++d)for(std::size_t i=0;i<raw[d].size();++i){appendDouble(result.pulse,raw[d][i]);appendDouble(result.pulse,onsets[d][i]);appendDouble(result.pulse,positions[d][i][0]);appendDouble(result.pulse,positions[d][i][1]);appendFloat(result.hits[d],positions[d][i][0]);appendFloat(result.hits[d],positions[d][i][1]);}
    for(const auto& detector:origins)for(const auto& origin:detector){result.pulse.push_back(static_cast<char>(origin[0]));result.pulse.push_back(static_cast<char>(origin[1]));}
    // Shared non-optical event tree, independent of display/trajectory budgets.
    std::vector<std::string> processes;std::map<std::string,uint32_t> processIds;
    for(const auto& node:state.history)if(!processIds.count(node.process)){processIds[node.process]=static_cast<uint32_t>(processes.size());processes.push_back(node.process);}
    const auto dictionary=json(processes).dump();auto& provenance=result.provenance;
    provenance.reserve(24+dictionary.size()+128*state.history.size()+4*(historyRefs[0].size()+historyRefs[1].size()));
    appendU64(provenance,state.id);appendU32(provenance,static_cast<uint32_t>(state.history.size()));
    for(const auto& refs:historyRefs)appendU32(provenance,static_cast<uint32_t>(refs.size()));
    appendU32(provenance,static_cast<uint32_t>(dictionary.size()));provenance+=dictionary;
    for(const auto& node:state.history){
        for(auto value:{node.parent,node.track,node.parentTrack,node.primary,node.component,node.nextComponent,static_cast<uint32_t>(node.pdg),processIds.at(node.process)})appendU32(provenance,value);
        appendDouble(provenance,node.time);appendVector(provenance,node.position);appendDouble(provenance,node.energyBefore);appendDouble(provenance,node.energyAfter);
        appendVector(provenance,node.directionBefore);appendVector(provenance,node.directionAfter);
    }
    for(const auto& refs:historyRefs)for(auto ref:refs)appendU32(provenance,ref);
    if(state.sampleTrajectory){result.preview=std::move(onsets);result.arrivals=std::move(raw);result.origins=std::move(origins);}
    require(out.size() == 324, "Internal event record size mismatch"); return result;
}
static std::string base64(const std::string& input) {
    static constexpr char alphabet[]="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string out; out.reserve((input.size()+2)/3*4);
    for (std::size_t i=0;i<input.size();i+=3) {
        const unsigned a=static_cast<unsigned char>(input[i]);
        const unsigned b=i+1<input.size()?static_cast<unsigned char>(input[i+1]):0;
        const unsigned c=i+2<input.size()?static_cast<unsigned char>(input[i+2]):0;
        out.push_back(alphabet[a>>2]); out.push_back(alphabet[((a&3)<<4)|(b>>4)]);
        out.push_back(i+1<input.size()?alphabet[((b&15)<<2)|(c>>6)]:'='); out.push_back(i+2<input.size()?alphabet[c&63]:'=');
    }
    return out;
}
class OrderedWriter {
    struct Output { std::string role, batch, analog; std::array<std::string,2> hits; std::ofstream file; std::map<std::string,std::chrono::steady_clock::time_point> previewTimes; std::map<std::string,int> savedPreviews; std::array<double,2> maxima{}, eligibleMaxima{}; std::array<uint64_t,2> interactions{}, responses{}, eligibleResponses{}; std::array<std::array<uint64_t,4>,2> pulseOrigins{}; };
    struct Record {
        std::vector<std::string> events,pulses,provenance;
        std::vector<std::array<uint32_t,3>> checksums;
        std::vector<std::array<std::string,2>> hits;
        std::vector<AnalogEvent> previews;
        std::map<int,PreviewTrack> tracks;
        int id=0;
        std::size_t bytes() const {
            std::size_t n=0;for(const auto& e:events)n+=e.size();for(const auto& p:pulses)n+=p.size();for(const auto& p:provenance)n+=p.size();
            for(const auto& a:hits)for(const auto& h:a)n+=h.size();
            for(const auto& t:tracks)n+=sizeof(PreviewTrack)+t.second.points.capacity()*sizeof(G4ThreeVector);
            for(const auto& p:previews){for(int d=0;d<2;++d)n+=8*(p.preview[d].capacity()+p.arrivals[d].capacity())+2*p.origins[d].capacity();n+=p.births.size()*64;}
            return n;
        }
    };
    const Configuration& c; const fs::path cancellationFile;
    std::vector<Output> outputs;
    mutable std::mutex mutex; std::condition_variable ready; std::map<int, Record> pending; std::map<int, int> workerCounts;
    std::size_t pendingBytes = 0, peakBytes = 0, peakEvents = 0; int completed = 0;
    std::atomic<bool> cancelled{false};
    PreviewPublisher previews;
    const bool timing=std::getenv("TWINPALS_PROFILE_RUNTIME")!=nullptr;
    std::atomic<uint64_t> transportNs{0},encodingNs{0},waitingNs{0},publicationNs{0};
    static uint64_t nanoseconds(std::chrono::steady_clock::time_point start){return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-start).count();}
    std::chrono::steady_clock::time_point lastProgress = std::chrono::steady_clock::now();
    bool liveAnalysis;
    std::array<uint64_t,2> cascadeInteractions{}, cascadeResponses{};
    static bool interacts(const std::string& e,int d) {uint32_t flags;double energy;std::memcpy(&flags,e.data()+132+d*96,4);std::memcpy(&energy,e.data()+132+d*96+12,8);return (flags&2)||energy>0;}
    static bool responds(const std::string& e,int d) {uint64_t hits;std::memcpy(&hits,e.data()+132+d*96+4,8);return hits>0;}
    void flushBatch() {
        for (auto& output:outputs) {
            output.file.flush(); require(output.file.good(),"Stream flush failed");
            if (!output.batch.empty()) {
                const int count=static_cast<int>(output.batch.size()/324);
                emitProtocol({{"type","analysis_batch"},{"role",output.role},{"first",completed-count},{"count",count},{"data",base64(output.batch)},{"analog",base64(output.analog)},{"hit_a",base64(output.hits[0])},{"hit_b",base64(output.hits[1])}});
                output.batch.clear();output.analog.clear();
                output.hits[0].clear();output.hits[1].clear();
            }
        }
    }
static bool eligibleResponse(const std::string& bytes,int detector){uint32_t flags;std::memcpy(&flags,bytes.data()+132+detector*96,4);return (flags&5)==5;}
public:
    OrderedWriter(const Configuration& cfg, const fs::path& outputDirectory) : c(cfg), cancellationFile(outputDirectory / "cancel.flag"), liveAnalysis(cfg.document.value("output",json::object()).value("live_analysis",false)) {
        const auto& streams = c.document.at("streams"); require(streams.is_array() && streams.size() == (c.sourceRole == "co60" ? 2u : 1u), "Wrong number of output streams");
        for (const auto& stream : streams) {
            Output out; out.role = stream.at("role").get<std::string>(); const auto path = fs::u8path(stream.at("path").get<std::string>());
            require(path.extension() == ".part", "Native output must end .part");
            if (path.has_parent_path()) fs::create_directories(path.parent_path());
            out.file.open(path, std::ios::binary | std::ios::out | std::ios::trunc); require(out.file.good(), "Cannot create stream output");
            auto header = stream.at("header"); header["native"] = {{"worker_version", kWorkerVersion}, {"geant4_version", kEngineVersion}, {"seed", c.seed}, {"threads", c.threads}, {"rng_policy", kRngPolicy}, {"reflections_definition", "Optical boundary reflections from crystal and entrance window, all tracked photons of selected ancestry"}};
            header["version"] = 6;header["provenance_layout"]="shared-transport-tree-v1";
            header["light_components"]=lightComponents(c);
            header["physics"] = c.document.at("physics");
            header["analog_response"]=c.document.at("analog_response");
            header["photoelectron_layout"]="float64[PE,4]:arrival_ns,onset_ns,local_x_mm,local_y_mm;uint8[PE,2]:mechanism,component;mechanism:1=scintillation,2=cherenkov";
            header["native"]["optical_boundary_model"] = kOpticalBoundaryModel;
            const auto encoded = header.dump(); require(encoded.size() <= 64 * 1024 * 1024, "Header exceeds 64 MiB"); std::string prefix("TPSTRM06", 8); appendU32(prefix, static_cast<uint32_t>(encoded.size()));
            out.file.write(prefix.data(), static_cast<std::streamsize>(prefix.size())); out.file.write(encoded.data(), static_cast<std::streamsize>(encoded.size())); out.file.flush(); require(out.file.good(), "Cannot persist stream header");
            if (liveAnalysis) emitProtocol({{"type","analysis_header"},{"role",out.role},{"header",header}});
            outputs.push_back(std::move(out));
        }
    }
    void submit(EventState& state) {
        const auto begin=std::chrono::steady_clock::now();if(timing)transportNs+=nanoseconds(state.started);
        if(state.auditLight && (!state.acceptedOrigins[0].empty() || !state.acceptedOrigins[1].empty()))
            emitProtocol({{"type","light_origin_audit"},{"event_id",state.id},{"accepted",state.acceptedOrigins}});
        Record record;record.id=state.id;record.tracks=std::move(state.tracks);
        for (std::size_t i = 0; i < outputs.size(); ++i) {
            auto event=eventBytes(state,c.sourceRole=="co60"?static_cast<int>(i):-1,c);
            // Calculate immutable physical-frame checksums on the simulation
            // workers, before entering the ordered writer's critical section.
            record.checksums.push_back({crc32(event.pulse),crc32(event.provenance),crc32(event.event)});
            record.events.push_back(std::move(event.event));record.pulses.push_back(std::move(event.pulse));
            record.hits.push_back(std::move(event.hits));record.provenance.push_back(std::move(event.provenance));
            record.previews.push_back(std::move(event));
        }
        if(timing)encodingNs+=nanoseconds(begin);
        const auto waitBegin=std::chrono::steady_clock::now();
        std::unique_lock<std::mutex> lock(mutex); require(state.id >= completed && state.id < c.events && !pending.count(state.id), "Invalid event ordering");
        ready.wait(lock, [&] { return state.id == completed || (pending.size() < reorderEventLimit(c.threads) && pendingBytes + record.bytes() <= kReorderBytesLimit); });
        if(timing)waitingNs+=nanoseconds(waitBegin);
        const auto publishBegin=std::chrono::steady_clock::now();
        ++workerCounts[G4Threading::G4GetThreadId()];
        auto publish = [&](const Record& r) {
            if(c.sourceRole=="co60")for(int d=0;d<2;++d){cascadeInteractions[d]+=interacts(r.events[0],d)&&interacts(r.events[1],1-d);cascadeResponses[d]+=eligibleResponse(r.events[0],d)&&eligibleResponse(r.events[1],1-d);}
            for (std::size_t i = 0; i < outputs.size(); ++i) {
                auto& output=outputs[i];const auto& checksum=r.checksums[i];
                frame(output.file,"APLS",r.pulses[i],checksum[0]);frame(output.file,"PROV",r.provenance[i],checksum[1]);frame(output.file, "EVNT",r.events[i],checksum[2]);
                for(int d=0;d<2;++d){uint32_t flags;std::memcpy(&flags,r.events[i].data()+132+d*96,4);output.interactions[d]+=interacts(r.events[i],d);output.responses[d]+=responds(r.events[i],d);output.eligibleResponses[d]+=((flags&5)==5);++output.pulseOrigins[d][(flags>>4)&3];}
                if(liveAnalysis) {output.batch+=r.events[i];output.analog+=r.pulses[i];for(int d=0;d<2;++d)output.hits[d]+=r.hits[i][d];}
                for(int d=0;d<2;++d){double low,high;std::memcpy(&low,r.events[i].data()+132+d*96+80,8);std::memcpy(&high,r.events[i].data()+132+d*96+88,8);output.maxima[d]=std::max(output.maxima[d],std::max(-low,high));uint32_t flags;std::memcpy(&flags,r.events[i].data()+132+d*96,4);if(flags&4)output.eligibleMaxima[d]=std::max(output.eligibleMaxima[d],std::max(-low,high));}
                const auto& p=r.previews[i];
                if (!r.tracks.empty() || !p.preview[0].empty() || !p.preview[1].empty()) {
                    std::array<uint32_t,2> flags{};for(int d=0;d<2;++d)std::memcpy(&flags[d],r.events[i].data()+132+d*96,4);
                    const std::string outcome=interacts(r.events[i],0)||interacts(r.events[i],1)?"interaction":((flags[0]|flags[1])&8)?"transmission":"miss";
                    const auto category=outcome+"_"+std::to_string((flags[0]>>4)&3)+"_"+std::to_string((flags[1]>>4)&3);
                    const auto now=std::chrono::steady_clock::now();
                    if(output.savedPreviews[category]<c.trajectoryLimit || now-output.previewTimes[category]>=std::chrono::milliseconds(80)) {
                        output.previewTimes[category]=now;
                        // JSON is only a display representation. Construct it
                        // for selected previews, never for discarded events.
                        json tracks=json::array(),categories=json::object(),eligible=json::array();
                        for(const auto& t:r.tracks)if(c.sourceRole!="co60" || t.second.primary==i)tracks.push_back(t.second.encode());
                        for(int d=0;d<2;++d){categories[d?"B":"A"]=interacts(r.events[i],d)?"interaction":(flags[d]&8)?"transmission":"miss";eligible.push_back(bool(flags[d]&4));}
                        json preview={{"type","trajectory"},{"event_id",r.id},{"role",output.role},{"category",outcome},{"detectors",categories},{"energy_accepted",eligible},
                            {"tracks",std::move(tracks)},{"analog_onsets_ns",p.preview},{"cathode_arrivals_ns",p.arrivals},{"light_origins",p.origins},{"cherenkov_births",p.births}};
                        // Live samples roll continuously; durable preview frames remain bounded.
                        if(output.savedPreviews[category]<c.trajectoryLimit) {frame(output.file,"TRAK",preview.dump()); ++output.savedPreviews[category];}
                        // Only transmitted samples carry this temporary copy.
                        // The durable TRAK derives its ancestry from preceding PROV.
                        preview["ancestry_b64"]=base64(r.provenance[i]);
                        previews.push(preview);
                    }
                }
            }
            ++completed;
            const auto now = std::chrono::steady_clock::now();
            if (completed % 2048 == 0 || completed == c.events || now - lastProgress > std::chrono::milliseconds(150) || (liveAnalysis&&outputs[0].analog.size()>4*1024*1024)) {
                flushBatch();
                // Progress shares the ordered display queue. A synchronous
                // console write here would wait behind a large preview and
                // hold the transport writer lock again.
                previews.push({{"type", "progress"}, {"completed", completed}, {"total", c.events}}); lastProgress = now;
                if (fs::exists(cancellationFile)) cancelled = true;
            }
        };
        if (state.id == completed) { publish(record); while (true) { auto p = pending.find(completed); if (p == pending.end()) break; publish(p->second); pendingBytes -= p->second.bytes(); pending.erase(p); } }
        else { pendingBytes += record.bytes(); pending.emplace(state.id, std::move(record)); peakBytes = std::max(peakBytes, pendingBytes); peakEvents = std::max(peakEvents, pending.size()); }
        ready.notify_all();
        if(timing)publicationNs+=nanoseconds(publishBegin);
        if (cancelled) G4RunManager::GetRunManager()->AbortRun(true);
    }
    json finish() {
        previews.close();
        require(previews.succeeded(),"Preview publication failed");
        std::lock_guard<std::mutex> lock(mutex); require(pending.empty(), "Unwritten events in reorder queue"); require(cancelled || completed == c.events, "Incomplete simulation output");
        const std::string status = cancelled ? "cancelled" : "completed";
        flushBatch();
        for (auto& output : outputs) {
            json done={{"status",status},{"events",completed},{"observed_maximum_mV",output.maxima},{"eligible_maximum_mV",output.eligibleMaxima},
                {"detector_counts",{{"interaction",output.interactions},{"response",output.responses}}},{"eligible_response_counts",output.eligibleResponses},{"pulse_origin_counts",output.pulseOrigins}};
            if(c.sourceRole=="co60")done["cascade_pair_counts"]={{"interaction",cascadeInteractions},{"response",cascadeResponses}};
            frame(output.file,"DONE",done.dump());output.file.flush();require(output.file.good(),"Final stream flush failed");output.file.close();
        }
        json counts = json::object(); for (const auto& p : workerCounts) counts[std::to_string(p.first)] = p.second;
        json result={{"type", "finished"}, {"status", status}, {"completed", completed}, {"worker_event_counts", counts}, {"threads_observed", workerCounts.size()}, {"reorder_pending_bytes_peak", peakBytes}, {"reorder_pending_events_peak", peakEvents}};
        if(timing)result["runtime_timing_seconds"]={{"transport_worker_sum",transportNs.load()/1e9},{"encoding_worker_sum",encodingNs.load()/1e9},{"waiting_worker_sum",waitingNs.load()/1e9},{"publication_serial",publicationNs.load()/1e9}};
        return result;
    }
};
class Events final : public G4UserEventAction {
    std::shared_ptr<EventState> owner; EventState& state; OrderedWriter& writer;
public:
    Events(std::shared_ptr<EventState> event, OrderedWriter& w) : owner(std::move(event)), state(*owner), writer(w) {}
    void EndOfEventAction(const G4Event* event) override { require(!event->IsAborted(), "Aborted event is not complete"); writer.submit(state); }
};
