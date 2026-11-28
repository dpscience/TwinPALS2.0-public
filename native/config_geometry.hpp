// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

struct CathodeFilm final : G4OpticalSurface {
    Curve n,k,escape;
    double thickness;
    CathodeFilm(const std::string& name,const json& film):
        G4OpticalSurface(name,glisur,polished,dielectric_metal),
        n(curve(film.at("n"),"Cathode refractive index",1.e-12,1.e6)),
        k(curve(film.at("k"),"Cathode extinction coefficient",0,1.e6)),
        escape(curve(film.at("escape"),"Photoemission probability",0,1)),
        thickness(number(film,"thickness_nm",1.e-12,1.e12)) {}
    static double sample(const Curve& rows,double energy) {
        auto hi=std::lower_bound(rows.begin(),rows.end(),energy,[](const auto& row,double e){return row.first<e;});
        if(hi==rows.begin())return hi->second;
        if(hi==rows.end())return rows.back().second;
        const auto lo=hi-1;
        return lo->second+(hi->second-lo->second)*(energy-lo->first)/(hi->first-lo->first);
    }
};

// Resolved Module 1 geometry. Every dimension is a full length in millimetres.
static G4ThreeVector readVector(const json& j, const std::string& label) {
    require(j.is_array() && j.size() == 3, label + " must contain three numbers");
    double p[3];
    for (int i = 0; i < 3; ++i) { require(j[i].is_number(), label + " must be numeric"); p[i] = j[i].get<double>(); require(std::isfinite(p[i]), label + " must be finite"); }
    return {p[0], p[1], p[2]};
}
static G4RotationMatrix rotationFor(const json& j) {
    auto z = readVector(j.value("axis", json::array({0, 0, 1})), "axis");
    require(z.mag2() > 1.e-12, "axis cannot be zero"); z = z.unit();
    auto up = readVector(j.value("up", json::array({0, 1, 0})), "up");
    if (std::abs(up.unit().dot(z)) > .9999) up = {1, 0, 0};
    require(up.mag2() > 1.e-12, "up cannot be zero");
    const auto x = up.cross(z).unit(), y = z.cross(x).unit();
    G4RotationMatrix result; result.rotateAxes(x, y, z); return result;
}
struct DetectorConfig {
    json data, dimensions, material, coupling, window, sensor, surface, pmt;
    std::string shape;
    G4ThreeVector front;
    G4RotationMatrix rotation;
    double length, couplingThickness, windowThickness, sideWrap, frontWrap;
    Curve domain, qe;
    std::vector<Curve> emissions;
    std::vector<json> components;
    explicit DetectorConfig(const json& j) : data(j) {
        shape = j.at("shape").get<std::string>();
        require(shape == "cone" || shape == "cylinder" || shape == "box" || shape == "pyramid", "Unknown crystal shape");
        dimensions = j.at("dimensions"); length = number(dimensions, "length_mm", .01, 500);
        front = readVector(j.at("front_mm"), "front_mm") * mm; rotation = rotationFor(j);
        material = j.at("material"); coupling = j.at("coupling"); window = j.at("window"); sensor = j.at("sensor"); surface = j.at("surface"); pmt=j.at("pmt");
        couplingThickness = number(coupling, "thickness_mm", 0, 100);
        windowThickness = number(window, "thickness_mm", .0001, 100);
        sideWrap = surface.value("enabled", true) ? optionalNumber(surface, "thickness_mm", .5, 0, 100) : 0;
        frontWrap = surface.value("enabled", true) ? optionalNumber(surface, "front_thickness_mm", .4, 0, 100) : 0;
        if (material.contains("components")) {
            require(material.at("components").is_array() && !material.at("components").empty() && material.at("components").size() <= 3, "Scintillator needs one to three components");
            for (const auto& component : material.at("components")) components.push_back(component);
        } else components.push_back({{"emission", material.at("emission")}, {"fraction", 1.}, {"rise_time_ns", material.at("rise_time_ns")}, {"decay_time_ns", material.at("decay_time_ns")}});
        double emin = 100, emax = 0, sum = 0;
        for (const auto& component : components) {
            auto spectrum = curve(component.at("emission"), "component emission", 0, 1.e12);
            require(std::any_of(spectrum.begin(), spectrum.end(), [](auto p) { return p.second > 0; }), "Empty emission component");
            emin = std::min(emin, spectrum.front().first); emax = std::max(emax, spectrum.back().first);
            number(component, "decay_time_ns", 1.e-9, 1.e8); optionalNumber(component, "rise_time_ns", 0, 0, 1.e8);
            sum += number(component, "fraction", 0, 1); emissions.push_back(std::move(spectrum));
        }
        require(std::abs(sum - 1.) < 1.e-6, "Scintillation component fractions must sum to one");
        domain = {{emin, 1}, {emax, 1}};
        qe = curve(sensor.at("qe"), "photocathode QE", 0, 1);
        number(material, "light_yield_per_MeV", 0, 200000); optionalNumber(material, "resolution_scale", 1, 0, 10);
        // Validate all requested shape dimensions before any Geant4 allocation.
        if (shape == "cone") { number(dimensions, "front_diameter_mm", .01, 1000); number(dimensions, "rear_diameter_mm", .01, 1000); }
        if (shape == "cylinder") number(dimensions, "diameter_mm", .01, 1000);
        if (shape == "box") { number(dimensions, "width_mm", .01, 1000); number(dimensions, "height_mm", .01, 1000); }
        if (shape == "pyramid") for (auto key : {"front_width_mm", "front_height_mm", "rear_width_mm", "rear_height_mm"}) number(dimensions, key, .01, 1000);
    }
};
struct Configuration {
    json document, sourceGeometry, samples, shields, streamHeaders;
    std::vector<DetectorConfig> detectors;
    std::string sourceRole;
    int events, seed, threads, trajectoryLimit, opticalTracksPerDetector;
    bool includeCherenkov;
    double minimumEnergyKeV;
    G4ThreeVector sourcePosition;
    G4RotationMatrix sourceRotation;
    double sourceRadius, sourceThickness;
    explicit Configuration(json j) : document(std::move(j)) {
        const auto& physics = document.at("physics");
        require(physics.at("include_cherenkov").is_boolean(), "Include Cherenkov must be a checkbox value");
        includeCherenkov = physics.at("include_cherenkov").get<bool>();
        minimumEnergyKeV = number(physics, "minimum_energy_keV", 0, std::numeric_limits<double>::max());
        events = static_cast<int>(number(document, "events", 1, 2147483646));
        seed = static_cast<int>(number(document, "seed", 1, 2147483646));
        threads = static_cast<int>(number(document, "threads", 1, 256));
        for (auto key : {"events", "seed", "threads"}) require(document.at(key).is_number_integer(), std::string(key) + " must be integral");
        sourceRole = document.at("source_role").get<std::string>();
        require(sourceRole == "na22_prompt" || sourceRole == "na22_annihilation" || sourceRole == "co60", "Invalid source_role");
        require(document.at("detectors").is_array() && document.at("detectors").size() == 2, "Exactly two detectors required");
        for (const auto& d : document.at("detectors")) detectors.emplace_back(d);
        sourceGeometry = document.value("source_geometry", json::object());
        sourcePosition = readVector(sourceGeometry.value("position_mm", json::array({0, 0, 0})), "source position") * mm;
        sourceRotation = rotationFor(sourceGeometry);
        sourceRadius = optionalNumber(sourceGeometry, "radius_mm", 0, 0, 1000);
        sourceThickness = optionalNumber(sourceGeometry, "thickness_mm", 0, 0, 1000);
        samples = document.value("blocks", json::array()); shields = document.value("shields", json::array());
        require(samples.is_array() && shields.is_array(), "Samples/shields must be arrays");
        trajectoryLimit = static_cast<int>(optionalNumber(document.value("output", json::object()), "trajectory_sample_limit", 20, 0, 10000));
        opticalTracksPerDetector = static_cast<int>(optionalNumber(document.value("output", json::object()), "optical_tracks_per_detector", 24, 0, 256));
        streamHeaders = document.value("stream_headers", json::array());
    }
};

class Geometry final : public G4VUserDetectorConstruction {
    const Configuration& c;
    std::vector<G4VPhysicalVolume*> placements;
    G4Material* compound(const std::string& name, const json& p) {
        auto* nist = G4NistManager::Instance();
        if (p.contains("nist_material") || p.contains("nist")) { auto* m = nist->FindOrBuildMaterial(p.value("nist_material", p.value("nist", std::string())), true, false); require(m != nullptr, name + ": unknown NIST material"); return m; }
        require(p.contains("composition") && p.at("composition").is_object() && !p.at("composition").empty(), name + ": composition required");
        const auto& composition = p.at("composition");
        auto* m = new G4Material(name, number(p, "density_g_cm3", 1.e-9, 100) * g / cm3, static_cast<int>(composition.size()));
        const auto mode = p.value("composition_basis", p.value("composition_mode", std::string("atoms")));
        double sum = 0;
        for (const auto& item : composition.items()) { require(item.value().is_number(), name + ": invalid composition"); double v = item.value().get<double>(); require(std::isfinite(v) && v > 0, name + ": nonpositive composition"); sum += v; }
        require(mode == "atoms" || mode == "mass_fraction", name + ": unsupported composition mode");
        bool fractionalAtoms = false;
        if (mode == "atoms") for (const auto& item : composition.items()) if (item.value().get<double>() != std::floor(item.value().get<double>())) fractionalAtoms = true;
        double molecularMass = 0;
        if (fractionalAtoms) for (const auto& item : composition.items()) {
            auto* element = nist->FindOrBuildElement(item.key(), true); require(element != nullptr, name + ": unknown element");
            molecularMass += item.value().get<double>() * element->GetA();
        }
        for (const auto& item : composition.items()) {
            auto* e = nist->FindOrBuildElement(item.key(), true); require(e != nullptr, name + ": unknown element");
            if (mode == "mass_fraction") m->AddElement(e, item.value().get<double>() / sum);
            else if (fractionalAtoms) m->AddElement(e, item.value().get<double>() * e->GetA() / molecularMass);
            else { const double v = item.value().get<double>(); require(v == std::floor(v) && v <= 1000000, name + ": atom counts must be positive integers"); m->AddElement(e, static_cast<int>(v)); }
        }
        return m;
    }
    G4Material* optical(const std::string& name, const json& p, const Curve& domain, bool scintillator = false, const DetectorConfig* d = nullptr) {
        auto* base = compound(name + "Base", p);
        auto* m = new G4Material(name, base->GetDensity(), base);
        auto* table = new G4MaterialPropertiesTable;
        require(p.contains("refractive_index"), name + ": refractive_index is required");
        addCurve(table, "RINDEX", opticalProperty(p, "refractive_index", 1, domain, 1, 10));
        if (p.contains("absorption_length_mm")) addCurve(table, "ABSLENGTH", opticalProperty(p, "absorption_length_mm", 1, domain, 1.e-9, 1.e15), mm);
        if (p.contains("rayleigh_length_mm")) addCurve(table, "RAYLEIGH", opticalProperty(p, "rayleigh_length_mm", 1, domain, 1.e-9, 1.e15), mm);
        if (scintillator) {
            for (std::size_t k = 0; k < d->components.size(); ++k) {
                const auto suffix = std::to_string(k + 1); const auto& component = d->components[k];
                addCurve(table, ("SCINTILLATIONCOMPONENT" + suffix).c_str(), d->emissions[k]);
                table->AddConstProperty(("SCINTILLATIONTIMECONSTANT" + suffix).c_str(), component.at("decay_time_ns").get<double>() * ns);
                table->AddConstProperty(("SCINTILLATIONRISETIME" + suffix).c_str(), component.value("rise_time_ns", 0.) * ns);
                table->AddConstProperty(("SCINTILLATIONYIELD" + suffix).c_str(), component.at("fraction").get<double>());
            }
            table->AddConstProperty("SCINTILLATIONYIELD", p.at("light_yield_per_MeV").get<double>() / MeV);
            table->AddConstProperty("RESOLUTIONSCALE", p.value("resolution_scale", 1.));
            if (p.contains("birks_mm_per_MeV")) m->GetIonisation()->SetBirksConstant(number(p, "birks_mm_per_MeV", 0, 100) * mm / MeV);
        }
        m->SetMaterialPropertiesTable(table); return m;
    }
    G4VSolid* crystal(const std::string& name, const DetectorConfig& d, double extension = 0) {
        const auto& x = d.dimensions; const double half = d.length * mm / 2.;
        if (d.shape == "cone") {
            return new G4Cons(name,0,(x.at("front_diameter_mm").get<double>()/2+extension)*mm,
                             0,(x.at("rear_diameter_mm").get<double>()/2+extension)*mm,half,0,twopi);
        }
        if (d.shape == "cylinder") return new G4Tubs(name, 0, (x.at("diameter_mm").get<double>() / 2 + extension) * mm, half, 0, twopi);
        if (d.shape == "box") return new G4Box(name, (x.at("width_mm").get<double>() / 2 + extension) * mm, (x.at("height_mm").get<double>() / 2 + extension) * mm, half);
        return new G4Trd(name, (x.at("front_width_mm").get<double>() / 2 + extension) * mm, (x.at("rear_width_mm").get<double>() / 2 + extension) * mm, (x.at("front_height_mm").get<double>() / 2 + extension) * mm, (x.at("rear_height_mm").get<double>() / 2 + extension) * mm, half);
    }
    G4VSolid* endFace(const std::string& name, const DetectorConfig& d, double length, bool front = false, const json& aperture = json::object()) {
        const auto& x = d.dimensions;
        if (aperture.value("shape", std::string()) == "rect")
            return new G4Box(name, number(aperture,"width_mm",.001,1000)*mm/2., number(aperture,"height_mm",.001,1000)*mm/2.,length*mm/2.);
        if (aperture.contains("diameter_mm")) return new G4Tubs(name, 0, number(aperture, "diameter_mm", .001, 1000) * mm / 2., length * mm / 2., 0, twopi);
        if (d.shape == "cone" || d.shape == "cylinder") {
            double diameter = x.at(d.shape == "cylinder" ? "diameter_mm" : front ? "front_diameter_mm" : "rear_diameter_mm").get<double>();
            return new G4Tubs(name, 0, diameter * mm / 2., length * mm / 2., 0, twopi);
        }
        double width = x.at(d.shape == "box" ? "width_mm" : front ? "front_width_mm" : "rear_width_mm").get<double>();
        double height = x.at(d.shape == "box" ? "height_mm" : front ? "front_height_mm" : "rear_height_mm").get<double>();
        return new G4Box(name, aperture.value("width_mm", width) * mm / 2., aperture.value("height_mm", height) * mm / 2., length * mm / 2.);
    }
    G4VSolid* sideShell(const std::string& name,const DetectorConfig& d) {
        const auto& x=d.dimensions;const double half=d.length*mm/2,thickness=d.sideWrap*mm;
        if(d.shape=="cone") {
            const double front=x.at("front_diameter_mm").get<double>()*mm/2,rear=x.at("rear_diameter_mm").get<double>()*mm/2;
            return new G4Cons(name,front,front+thickness,rear,rear+thickness,half,0,twopi);
        }
        if(d.shape=="cylinder") {
            const double radius=x.at("diameter_mm").get<double>()*mm/2;
            return new G4Tubs(name,radius,radius+thickness,half,0,twopi);
        }
        // The subtraction extends only through the end planes; tapered sides
        // must retain their exact original slope, including future dimensions.
        const double extra=1.e-6*mm;
        G4VSolid* inner;
        if(d.shape=="box") inner=new G4Box(name+"Inner",x.at("width_mm").get<double>()*mm/2,x.at("height_mm").get<double>()*mm/2,half+extra);
        else {
            const double xf=x.at("front_width_mm").get<double>()*mm/2,xr=x.at("rear_width_mm").get<double>()*mm/2;
            const double yf=x.at("front_height_mm").get<double>()*mm/2,yr=x.at("rear_height_mm").get<double>()*mm/2;
            const double dx=extra*(xr-xf)/(2*half),dy=extra*(yr-yf)/(2*half);
            inner=new G4Trd(name+"Inner",xf-dx,xr+dx,yf-dy,yr+dy,half+extra);
        }
        return new G4SubtractionSolid(name,crystal(name+"Outer",d,d.sideWrap),inner);
    }
    G4VPhysicalVolume* place(const std::string& name, G4VSolid* s, G4Material* m, const G4Transform3D& t, G4LogicalVolume* mother, int copy = 0) {
        auto* l = new G4LogicalVolume(s, m, name + "Logical"); auto* p = new G4PVPlacement(t, l, name, mother, false, copy, false); placements.push_back(p); return p;
    }
    G4OpticalSurface* wrapSurface(const std::string& id, const DetectorConfig& d) {
        const auto model = d.surface.value("model", std::string("unified"));
        require(model == "unified" || model == "lut", "Unsupported wrapping model");
        G4OpticalSurface* s;
        if (model == "lut") {
            const char* path = std::getenv("G4REALSURFACEDATA");
            require(path && fs::exists(path), "LUT wrapping requires the G4RealSurface dataset (G4REALSURFACEDATA)");
            s = new G4OpticalSurface("WrapOptics" + id, LUT, polishedteflonair, dielectric_LUT);
        } else { s = new G4OpticalSurface("WrapOptics" + id, unified, ground, dielectric_metal); s->SetSigmaAlpha(optionalNumber(d.surface, "sigma_alpha_rad", .1, 0, 1)); }
        auto* p = new G4MaterialPropertiesTable;
        // The archived LBNL LUT surface had an empty surface property table.
        // Scalar survival/reflection controls belong only to the unified model.
        if (model == "unified") {
            addCurve(p, "REFLECTIVITY", opticalProperty(d.surface, "reflectivity", .98, d.domain, 0, 1));
            addCurve(p, "EFFICIENCY", {{d.domain.front().first, 0}, {d.domain.back().first, 0}});
            addCurve(p, "SPECULARLOBECONSTANT", {{d.domain.front().first, 1}, {d.domain.back().first, 1}});
        }
        s->SetMaterialPropertiesTable(p); return s;
    }
    void blocks(const json& array, const std::string& prefix, G4LogicalVolume* world) {
        for (std::size_t i = 0; i < array.size(); ++i) {
            const auto& b = array[i]; if (!b.value("enabled", true)) continue;
            const auto name = prefix + "_" + b.value("id", std::to_string(i)); const auto shape = b.value("shape", std::string("box"));
            const double t = number(b, "thickness_mm", .000001, 1000); G4VSolid* s;
            if (shape == "cylinder") s = new G4Tubs(name + "Solid", 0, number(b, "diameter_mm", .001, 10000) * mm / 2, t * mm / 2, 0, twopi);
            else { require(shape == "box", "Sample/shield shape must be box or cylinder"); s = new G4Box(name + "Solid", number(b, "width_mm", .001, 10000) * mm / 2, number(b, "height_mm", .001, 10000) * mm / 2, t * mm / 2); }
            place(name, s, compound(name + "Material", b.at("material")), G4Transform3D(rotationFor(b), readVector(b.at("position_mm"), name + " position") * mm), world);
        }
    }
public:
    std::array<G4VPhysicalVolume*, 2> detectors{}, sensors{}, windows{};
    explicit Geometry(const Configuration& cfg) : c(cfg) {}
    bool acceptsQeEnergy(int detector, double energy) const { return qeContains(c.detectors[detector].qe, energy); }
    G4ThreeVector localPoint(int d, const G4ThreeVector& world) const { return c.detectors[d].rotation.inverse() * (world - c.detectors[d].front); }
    G4VPhysicalVolume* Construct() override {
        auto* nist = G4NistManager::Instance();
        auto* air = new G4Material("TPWorldAir", .00120479 * g / cm3, nist->FindOrBuildMaterial("G4_AIR"));
        auto* airProps = new G4MaterialPropertiesTable; addCurve(airProps, "RINDEX", {{.1, 1.00027}, {20, 1.00027}}); air->SetMaterialPropertiesTable(airProps);
        double extent = 2000.;
        for (const auto& d : c.detectors) extent = std::max(extent, d.front.mag() / mm + d.length + d.couplingThickness + number(d.pmt,"tube_length_mm",.1,2000) + (d.pmt.value("tube_shape",std::string("circle"))=="square" ? number(d.pmt,"tube_width_mm",.1,1000)/std::sqrt(2.) : number(d.pmt,"tube_diameter_mm",.1,1000)/2) + 1000.);
        for (const auto& array : {c.samples, c.shields}) for (const auto& b : array) if (b.value("enabled", true)) extent = std::max(extent, readVector(b.at("position_mm"), "block position").mag() + 10000.);
        auto* worldLogical = new G4LogicalVolume(new G4Box("WorldSolid", extent * mm, extent * mm, extent * mm), air, "WorldLogical");
        auto* world = new G4PVPlacement(nullptr, {}, worldLogical, "World", nullptr, false, 0);
        for (int i = 0; i < 2; ++i) {
            const auto& d = c.detectors[i]; const std::string id = i ? "B" : "A";
            auto transform = [&](double z) { return G4Transform3D(d.rotation, d.front + d.rotation * G4ThreeVector(0, 0, z * mm)); };
            // Side wrapping is an open-ended sibling shell. A wrapping mother
            // touching the crystal end faces would also reflect the rear face,
            // incorrectly blocking the intended optical coupling.
            auto* wrapMaterial=(d.sideWrap>0||d.frontWrap>0)?compound("TPWrap"+id,d.surface.value("material",json{{"nist_material","G4_TEFLON"}})):nullptr;
            detectors[i] = place("Scint" + id, crystal("ScintSolid" + id, d), optical("TPScint" + id, d.material, d.domain, true, &d), transform(d.length / 2),worldLogical,i);
            if (d.sideWrap > 0 || d.frontWrap > 0) {
                auto* s = wrapSurface(id, d);
                if(d.sideWrap>0) {auto* sideWrapping=place("Wrap"+id,sideShell("WrapSolid"+id,d),wrapMaterial,transform(d.length/2),worldLogical);new G4LogicalBorderSurface("ScintToWrap"+id,detectors[i],sideWrapping,s);}
                if (d.frontWrap > 0) { auto* wrap = place("WrapFront" + id, endFace("WrapFrontSolid" + id, d, d.frontWrap, true), wrapMaterial, transform(-d.frontWrap / 2), worldLogical); new G4LogicalBorderSurface("ScintToFrontWrap" + id, detectors[i], wrap, s); }
            }
            if (d.couplingThickness > 0) place("Coupling" + id, endFace("CouplingSolid" + id, d, d.couplingThickness, false, d.coupling), optical("TPCoupling" + id, d.coupling, d.domain), transform(d.length + d.couplingThickness / 2), worldLogical);
            const double tubeLength=number(d.pmt,"tube_length_mm",.1,2000), gap=number(d.pmt,"cathode_gap_mm",0,1000);
            constexpr double sensorThickness=.05;
            require(tubeLength>d.windowThickness+gap+sensorThickness,"PMT dimensions leave no vacuum behind the cathode");
            auto* vacuum=new G4Material("PMTVacuumMaterial"+id,1.,1.01*g/mole,universe_mean_density,kStateGas,2.73*kelvin,3.e-18*pascal);
            auto* vp=new G4MaterialPropertiesTable; addCurve(vp,"RINDEX",{{.1,1.},{20,1.}});vacuum->SetMaterialPropertiesTable(vp);
            G4VSolid* envelope;
            if (d.pmt.value("tube_shape",std::string("circle"))=="square") {
                const double half=number(d.pmt,"tube_width_mm",.1,1000)*mm/2;
                envelope=new G4Box("PMTEnvelopeSolid"+id,half,half,tubeLength*mm/2);
            } else {
                const double radius=number(d.pmt,"tube_diameter_mm",.1,1000)*mm/2;
                envelope=new G4Tubs("PMTEnvelopeSolid"+id,0,radius,tubeLength*mm/2,0,twopi);
            }
            auto* tube=place("PMTEnvelope"+id,envelope,vacuum,transform(d.length+d.couplingThickness+tubeLength/2),worldLogical);
            auto local=[&](double z){return G4Transform3D(G4RotationMatrix(),G4ThreeVector(0,0,z*mm));};
            windows[i]=place("Window"+id,endFace("WindowSolid"+id,d,d.windowThickness,false,d.window),optical("TPWindow"+id,d.window,d.domain),local(-tubeLength/2+d.windowThickness/2),tube->GetLogicalVolume());
            // The entire bore behind the window is vacuum. The schematic shell
            // is drawn by the UI only; no invented glass wall enters transport.
            sensors[i]=place("Cathode"+id,endFace("CathodeSolid"+id,d,sensorThickness,false,d.sensor),nist->FindOrBuildMaterial("G4_Al"),local(-tubeLength/2+d.windowThickness+gap+sensorThickness/2),tube->GetLogicalVolume(),i);
            auto* surface=d.sensor.contains("film")
                ? static_cast<G4OpticalSurface*>(new CathodeFilm("CathodeOptics"+id,d.sensor.at("film")))
                : new G4OpticalSurface("CathodeOptics"+id,glisur,polished,dielectric_metal);auto* qp=new G4MaterialPropertiesTable;
            addQeCurve(qp,d.sensor.contains("film") ? curve(d.sensor.at("film").at("fallback"),"Outside film band QE",0,1) : d.qe);addCurve(qp,"REFLECTIVITY",{{.001,0},{1.e6,0}});surface->SetMaterialPropertiesTable(qp);
            new G4LogicalBorderSurface("WindowToCathode"+id,windows[i],sensors[i],surface);
            new G4LogicalBorderSurface("VacuumToCathode"+id,tube,sensors[i],surface);

        }
        blocks(c.samples, "Sample", worldLogical); blocks(c.shields, "Shield", worldLogical); return world;
    }
    void validateOverlaps() { for (auto* p : placements) require(!p->CheckOverlaps(2000, .000001 * mm, false, 10), "Geometry overlaps at " + p->GetName()); }
};
