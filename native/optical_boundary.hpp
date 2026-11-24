// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

// Keep exactly grazing reflections on the incident side of the boundary.
// The LBNL LUT has angular grid endpoints at 90 degrees. Floating-point
// rotations can accept these as inward although they are geometrically tangent.
// A tangent on a convex surface has no forward chord from the boundary itself.
// Resolve only that roundoff-degenerate direction towards the incident volume,
// by the smallest tested angle giving a chord through the solid's interior.
// Never move the point behind the navigator's back or kill a valid photon.
static bool reflectionStatus(G4OpBoundaryProcessStatus status) {
    return (status >= FresnelReflection && status <= BackScattering) ||
        (status >= PolishedLumirrorAirReflection && status <= GroundVM2000GlueReflection) || status == CoatedDielectricReflection;
}

static bool resolveGrazingReflection(const G4VSolid& solid, const G4ThreeVector& point,
                                      const G4ThreeVector& direction, G4ThreeVector& corrected) {
    if (solid.Inside(point) != kSurface) return false;
    const auto normal = solid.SurfaceNormal(point);
    constexpr double roundoff = 128 * std::numeric_limits<double>::epsilon();
    if (std::abs(direction.dot(normal)) > roundoff) return false;
    const auto* tolerances=G4GeometryTolerance::GetInstance();
    const double tolerance=tolerances->GetSurfaceTolerance();
    // At a finite edge, a side-tangent ray can legitimately leave through an
    // end/adjacent face (for example toward the coupling). It has no interior
    // chord because it is leaving, not because it is trapped on the curved side.
    // Use solid bounds, not a material ID or cone-specific dimension.
    G4ThreeVector lower,upper;solid.BoundingLimits(lower,upper);
    for(int axis=0;axis<3;++axis) {
        if(direction[axis]>roundoff && point[axis]>=upper[axis]-16*tolerance) return false;
        if(direction[axis]<-roundoff && point[axis]<=lower[axis]+16*tolerance) return false;
    }
    for (double angle=std::max(2*roundoff,4*tolerances->GetAngularTolerance()); angle<=.001; angle*=2) {
        corrected = (direction-angle*normal).unit();
        const double chord=solid.DistanceToOut(point,corrected);
        if (chord>16*tolerance && chord<kInfinity && solid.Inside(point+.5*chord*corrected)==kInside) return true;
    }
    std::ostringstream context;
    context << "Cannot resolve a grazing optical reflection at " << solid.GetName()
            << ": point " << point << ", direction " << direction << ", normal " << normal;
    throw std::runtime_error(context.str());
}

struct LutAngle {
    int theta,phi;
    double cumulative;
};
struct LutDistribution {
    std::vector<LutAngle> bins;
    // Monotone offsets into the original cumulative weights. The final
    // comparison is still against the original double, including at a knot.
    static constexpr size_t slices=128;
    std::array<size_t,slices+1> first{};
};
static LutDistribution lutDistribution(G4OpticalSurface& surface,int incident) {
    LutDistribution result;double sum=0;
    // Geant4 rejects outgoing.normal <= 0 after rotating these grid directions.
    // theta=0 or phi=0 is exactly -90 degrees: its normal component is zero.
    // Exclude those endpoints analytically, before rotations can round zero to
    // a tiny positive value and admit a tangent ray. All interior weights stay
    // unchanged; this is the LUT conditioned on the intended inward hemisphere.
    for(int theta=1;theta<surface.GetThetaIndexMax()-1;++theta)
        for(int phi=1;phi<surface.GetPhiIndexMax()-1;++phi) {
            const double weight=std::min(1.,surface.GetAngularDistributionValue(incident,theta,phi));
            if(weight>0) {sum+=weight;result.bins.push_back({theta,phi,sum});}
        }
    require(!result.bins.empty(),"Wrapping LUT has no reflection probability at this incident angle");
    size_t first=0;
    for(size_t i=0;i<=LutDistribution::slices;++i){
        const double target=(static_cast<double>(i)/LutDistribution::slices)*sum;
        while(first<result.bins.size() && result.bins[first].cumulative<=target)++first;
        result.first[i]=first;
    }
    return result;
}
static const LutAngle& sampleLut(const LutDistribution& distribution,double uniform) {
    const auto& bins=distribution.bins;
    const size_t slice=std::min(static_cast<size_t>(uniform*LutDistribution::slices),LutDistribution::slices-1);
    const double target=uniform*bins.back().cumulative;
    const auto found=std::upper_bound(bins.begin()+distribution.first[slice],bins.begin()+distribution.first[slice+1],target,
        [](double value,const LutAngle& bin){return value<bin.cumulative;});
    return found==bins.end()?bins.back():*found;
}

static G4ThreeVector lutDirection(const G4ThreeVector& incoming,const G4ThreeVector& normal,
                                 double incidence,const LutAngle& bin,double tolerance) {
    auto outgoing=-incoming;auto thetaAxis=outgoing.cross(normal);
    if(thetaAxis.mag()<tolerance)thetaAxis=outgoing.orthogonal();
    outgoing.rotate(incidence-(-90+4*bin.theta)*CLHEP::deg,thetaAxis);
    const auto phiAxis=thetaAxis.cross(outgoing);
    outgoing.rotate(-(-90+5*bin.phi)*CLHEP::deg,phiAxis);
    return outgoing.unit();
}

class OpticalBoundary final : public G4OpBoundaryProcess {
    std::unordered_map<G4OpticalSurface*,std::array<std::unique_ptr<LutDistribution>,91>> distributions;
    struct Interface {
        const G4VPhysicalVolume *pre=nullptr,*post=nullptr;
        G4OpticalSurface* measured=nullptr;
    };
    // One immutable geometry per native job. Cache both ordinary and measured
    // interfaces per worker. Checking both volume pointers handles collisions.
    std::array<Interface,64> interfaces{};
    G4OpticalSurface* measuredSurface(G4VPhysicalVolume* pre,G4VPhysicalVolume* post){
        const size_t slot=((reinterpret_cast<uintptr_t>(pre)>>5)^(reinterpret_cast<uintptr_t>(post)>>6))%interfaces.size();
        auto& entry=interfaces[slot];
        if(entry.pre==pre && entry.post==post)return entry.measured;
        auto* border=G4LogicalBorderSurface::GetSurface(pre,post);
        auto* surface=border?dynamic_cast<G4OpticalSurface*>(border->GetSurfaceProperty()):nullptr;
        entry={pre,post,nullptr};
        if(surface && surface->GetType()==dielectric_LUT && surface->GetModel()==LUT){
            auto* table=surface->GetMaterialPropertiesTable();
            if(!table || !(table->GetProperty(kREFLECTIVITY)||table->GetProperty(kTRANSMITTANCE)||table->GetProperty(kEFFICIENCY)))entry.measured=surface;
        }
        return entry.measured;
    }
    bool usedLut=false;
    G4OpBoundaryProcessStatus lutStatus=Undefined;
    bool sampleMeasuredWrapping(const G4Track& track,const G4Step& step) {
        const double tolerance=G4GeometryTolerance::GetInstance()->GetSurfaceTolerance();
        if(step.GetPostStepPoint()->GetStepStatus()!=fGeomBoundary || step.GetStepLength()<=tolerance) return false;
        auto* pre=step.GetPreStepPoint()->GetPhysicalVolume();auto* post=step.GetPostStepPoint()->GetPhysicalVolume();
        if(!pre || !post) return false;
        auto* surface=measuredSurface(pre,post);
        if(!surface)return false;
        auto* material=step.GetPreStepPoint()->GetMaterial()->GetMaterialPropertiesTable();
        if(!material || !material->GetProperty(kRINDEX)) return false;
        G4bool valid=false;
        auto normal=-G4TransportationManager::GetTransportationManager()->GetNavigatorForTracking()->GetGlobalExitNormal(step.GetPostStepPoint()->GetPosition(),&valid);
        if(!valid) return false;
        const auto incoming=track.GetMomentumDirection();
        if(incoming.dot(normal)>0)normal=-normal;
        const double incidence=incoming.angle(-normal);
        const int incident=std::clamp(static_cast<int>(std::lrint(incidence/CLHEP::deg)),0,90);
        auto& cached=distributions[surface][incident];
        if(!cached)cached=std::make_unique<LutDistribution>(lutDistribution(*surface,incident));
        const auto& distribution=*cached;
        G4ThreeVector outgoing;
        do {
            const auto& bin=sampleLut(distribution,G4UniformRand());
            // Angular transform follows Geant4 11.4.0 DielectricLUT (Geant4
            // Software License; its attribution is shipped with the runtime).
            // Same tabulated directions, rotations and inward-hemisphere
            // rejection as Geant4. Inverse-CDF replaces only its expensive
            // uniform-grid rejection loop; probabilities are unchanged.
            outgoing=lutDirection(incoming,normal,incidence,bin,tolerance);
        } while(outgoing.dot(normal)<=128*std::numeric_limits<double>::epsilon());
        const auto facet=(outgoing-incoming).unit();
        const auto polarization=-track.GetPolarization()+2*track.GetPolarization().dot(facet)*facet;
        aParticleChange.Initialize(track);aParticleChange.ProposeVelocity(track.GetVelocity());
        aParticleChange.ProposeMomentumDirection(outgoing.unit());aParticleChange.ProposePolarization(polarization.unit());
        lutStatus=G4OpBoundaryProcessStatus(int(surface->GetFinish())+(int(NoRINDEX)-int(groundbackpainted)));
        return true;
    }
public:
    G4OpBoundaryProcessStatus GetStatus() const override {return usedLut?lutStatus:G4OpBoundaryProcess::GetStatus();}
    G4VParticleChange* PostStepDoIt(const G4Track& track, const G4Step& step) override try {
        usedLut=sampleMeasuredWrapping(track,step);
        auto* result = usedLut?G4VDiscreteProcess::PostStepDoIt(track,step):G4OpBoundaryProcess::PostStepDoIt(track, step);
        if (!reflectionStatus(GetStatus())) return result;
        auto* change = static_cast<G4ParticleChange*>(result);
        const auto* pre = step.GetPreStepPoint();
        if (!pre->GetPhysicalVolume()) return result;
        const auto transform = pre->GetTouchableHandle()->GetHistory()->GetTopTransform();
        const auto point = transform.TransformPoint(step.GetPostStepPoint()->GetPosition());
        const auto direction = transform.TransformAxis(*change->GetMomentumDirection());
        G4ThreeVector corrected;
        if (resolveGrazingReflection(*pre->GetPhysicalVolume()->GetLogicalVolume()->GetSolid(), point, direction, corrected)) {
            const auto globalDirection=transform.Inverse().TransformAxis(corrected);
            change->ProposeMomentumDirection(globalDirection);
            const auto polarization=*change->GetPolarization();
            change->ProposePolarization((polarization-globalDirection*polarization.dot(globalDirection)).unit());
        }
        return result;
    } catch(const std::exception& error) {
        emitProtocol({{"type","error"},{"message",error.what()}});
        throw;
    }
};
