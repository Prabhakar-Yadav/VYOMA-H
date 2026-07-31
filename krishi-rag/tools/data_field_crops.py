# -*- coding: utf-8 -*-
"""Cash crop, oilseed and pulse concepts.

Sources: TNAU Agritech, eagri PATH-272/PATH-371/ENTO-331, ICAR-IISR Lucknow,
SBI Coimbatore, ICAR-CICR, ICAR-DRMR Bharatpur, NIPHM AESA IPM packages,
PAU Package of Practices, ICAR-IIMR, CABI Plantwise.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_concepts import src, write_all

TNAU_C = ("tnau-crop", "https://agritech.tnau.ac.in/crop_protection/crop_prot_crop_diseases_agri.html",
          "TNAU Agritech Portal crop disease and pest index")
EAGRI_C = ("eagri-crop", "http://eagri.org/eagri50/ENTO331/lecture03/sorghum/001.html",
           "TNAU eagri ENTO-331 and PATH-272 course material")
NIPHM = ("niphm", "https://niphm.gov.in/IPMPackages/Chickpea.pdf",
         "NIPHM DPPQS AESA based IPM packages")
PAU = ("pau", "https://pau.edu/content/ccil/pf/pp_rabi.pdf",
       "PAU Ludhiana Package of Practices for Crops of Punjab")

CONCEPTS = [
    dict(
        f="sugarcane-red-rot", type="Disease", title="Sugarcane red rot",
        desc="Fungal stalk rot showing red internal tissue crossed by white bands and giving off a sour alcoholic smell.",
        tags="sugarcane, red-rot, fungal, stalk-rot", sci="Colletotrichum falcatum",
        crop="sugarcane", local="लाल सड़न, lal sadan, कंडुआ", urgency="emergency",
        sources=src([TNAU_C, EAGRI_C]),
        symptoms="""- Leaves in the crown **yellow and dry from the tip and margins downward**, the third and fourth leaves going first while the top leaves stay green.
- The whole clump droops and the cane becomes **light and hollow-sounding when tapped**.
- **Splitting the cane lengthwise shows the internal tissue turned dull red to brick red.**
- Crossing that red tissue are **distinct white patches or cross-bands running at right angles to the length of the stalk** — this banding is the defining sign.
- The split cane gives off a **sharp sour alcoholic smell**, like fermenting jaggery.
- The rind over affected internodes becomes dull and shrunken, and small dark specks appear on it.
- Cut nodes show reddening spreading through the node into the next internode.
- Affected canes snap easily at an internode and the crop lodges in patches.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Sugarcane wilt | Red rot shows **white cross-bands inside red tissue with a sour alcoholic smell**. Wilt shows hollow boat-shaped cavities and a uniformly dull reddish-brown pith. |""",
        matters="**The most destructive sugarcane disease in India.** It travels in the setts, so infected seed cane carries it into a clean field. Whole varieties have been withdrawn from cultivation after red rot epidemics.",
        nonchem="""- **Take setts only from a disease-free seed nursery**; this is the single decisive measure.
- Grow resistant varieties and change variety when a local epidemic starts.
- Remove and destroy affected clumps together with the root stubble.
- Provide drainage; waterlogged fields are worst hit.
- Rotate with rice or a non-host crop, and avoid ratooning an affected crop."""),

    dict(
        f="sugarcane-early-shoot-borer", type="Pest", title="Sugarcane early shoot borer",
        desc="Caterpillar killing young sugarcane shoots, producing a foul-smelling dead heart that pulls out easily.",
        tags="sugarcane, borer, caterpillar, dead-heart, insect", sci="Chilo infuscatellus",
        crop="sugarcane", local="अगेती तना छेदक, ageti tana chhedak", urgency="high",
        sources=src([TNAU_C, EAGRI_C]),
        symptoms="""- The **central shoot of a young cane dries into a straw-coloured spike while the outer leaves stay green** — a dead heart.
- The dried central shoot **pulls out with one easy tug**, and the base is soft and wet.
- The pulled base gives off a **strong foul rotten smell** — the reliable field check.
- A **bore hole sits at or just above ground level** on the shoot, often with a little frass at the mouth.
- Splitting the shoot shows a tunnel running down toward the base with a caterpillar inside.
- The caterpillar is dirty white with **five dark violet longitudinal stripes** along the body and a brown head.
- Affected clumps throw out **a crowded bunch of thin side tillers from the base**, giving a grassy look.
- Damage concentrates in the **first 60 days after planting** and in dry, light soils.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Top borer | Early shoot borer's dead heart **pulls out easily with a foul smell and the hole is at ground level**. Top borer's dead heart holds fast, is dark brown, and comes with rows of shot holes in the top leaves. |""",
        matters="Attacks in the first 60 days when the crop is establishing, so a heavy attack thins the stand permanently. Dry weather and light soils make it worse.",
        nonchem="""- **Irrigate at the recommended intervals**; the pest is far worse under dry conditions.
- Earth up the rows to cover the base and block egg-laying at ground level.
- Pull and destroy dead-heart shoots at weeding.
- Trash-mulch the inter-rows.
- Release *Trichogramma chilonis* egg parasitoids; run light traps for moths.
- Destroy stubble after harvest and avoid ratooning a heavily attacked crop."""),

    dict(
        f="cotton-pink-bollworm", type="Pest", title="Cotton pink bollworm",
        desc="Caterpillar boring into cotton bolls through a tiny plugged hole, causing rosetted flowers and double seeds.",
        tags="cotton, bollworm, pink-bollworm, caterpillar, insect",
        sci="Pectinophora gossypiella", crop="cotton",
        local="गुलाबी सुंडी, gulabi sundi, गुलाबी इल्ली", urgency="emergency",
        sources=src([TNAU_C, EAGRI_C]),
        symptoms="""- Flowers fail to open properly and the petals twist together into a **rosette shape, like a closed puckered bud** — the classic first sign.
- Bolls carry a **tiny entry hole that is plugged with frass and quickly heals over**, so the boll looks sound from outside.
- Opening a boll shows **tunnels through the lint and seeds, packed with frass**.
- **Two seeds joined together by the caterpillar's silk — the double seed** — is definitive when the boll is cut.
- The caterpillar is white when young and develops **broad pink bands across the back** as it matures.
- Affected bolls **open partially or stay tight and hard**, and the lint inside is stained and cut.
- Lint from damaged bolls is discoloured, weak and short-stapled.
- Damage builds late in the season and is heaviest in long-duration and ratooned crops.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| *Helicoverpa* boll damage | Pink bollworm leaves **a tiny plugged hole with the larva entirely inside and double seeds**. *Helicoverpa* makes a wide round hole with its body hanging outside. |""",
        matters="**Has broken Bt cotton resistance across central and south India.** Because the entry hole heals over, a farmer inspecting bolls from outside sees a clean crop while the lint inside is being destroyed.",
        nonchem="""- **Follow a strict crop termination date** and avoid extending or ratooning the crop; carry-over in late bolls is what sustains the population.
- Remove and destroy rosetted flowers and fallen bolls twice a week.
- Install pheromone traps at 5 per acre for monitoring and 20 per acre for mass trapping.
- Destroy crop residue and stubble immediately after the final pick.
- Deep summer ploughing to expose overwintering larvae.
- Avoid unapproved long-duration hybrids."""),

    dict(
        f="cotton-jassid", type="Pest", title="Cotton jassid hopper burn",
        desc="Leafhopper turning cotton leaf margins yellow then rusty red with upward cupping, working up from the lower leaves.",
        tags="cotton, jassid, leafhopper, sucking-pest, insect",
        sci="Amrasca biguttula biguttula", crop="cotton",
        local="हरा तेला, hara tela, फुदका, tudtude", urgency="high",
        sources=src([TNAU_C, EAGRI_C]),
        symptoms="""- Leaf **margins turn yellow in a band following the rim** of the leaf all the way round.
- The yellow band deepens to **rusty red and bronze, then dry brown and crisp** — hopper burn.
- Leaf margins **curl upward**, cupping the leaf, with a crinkled puckered surface.
- Damage moves **from the older lower leaves upward** while the top of the plant stays green.
- On the underside, **wedge-shaped pale green insects about 2 to 3 mm** sit along the veins, broad at the head and tapering behind.
- Nymphs are wingless and pale, and **run sideways or diagonally** when disturbed.
- Adults hop or fly off instantly when a leaf is turned over.
- Severely hit plants stay short and stunted with a bronzed dried-out lower canopy.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Potassium deficiency (lalya) | Jassid yellowing **starts at the leaf margin with downward cupping and live wedge-shaped hoppers on the underside**. Potassium deficiency reddens the whole leaf between the veins with no insects. |""",
        matters="One of the reasons hairy-leaved cotton varieties are bred. Because the insects sit only on the underside, a farmer checking leaf tops misses them entirely.",
        nonchem="""- Turn over lower leaves at every field visit.
- **Grow hairy or pubescent-leaved varieties**, which jassids strongly avoid.
- Yellow sticky traps to monitor build-up.
- Avoid synthetic pyrethroids, which cause jassid and whitefly resurgence.
- Conserve spiders, mirid bugs and lacewings.
- Destroy crop residue and volunteer cotton after harvest."""),

    dict(
        f="cotton-leaf-curl-virus", type="Disease", title="Cotton leaf curl virus",
        desc="Whitefly-borne begomovirus thickening cotton leaf veins and producing cup-shaped leafy enations on the leaf underside.",
        tags="cotton, virus, leaf-curl, begomovirus, whitefly-borne",
        sci="Cotton leaf curl virus", crop="cotton",
        local="पत्ती मरोड़ रोग, patti marod rog, CLCuD", urgency="emergency",
        sources=src([TNAU_C, PAU]),
        symptoms="""- **Veins on the leaf thicken and darken, standing out as raised ridges** when the leaf is held up to the light — the earliest reliable sign.
- Leaf margins curl **upward and inward**, cupping the leaf.
- **Small cup-shaped leafy outgrowths (enations) appear on the underside of the leaf along the main veins** — this is definitive for cotton leaf curl.
- Leaves become thick, leathery, dark green and brittle.
- Internodes shorten so the plant becomes **stunted and bushy** with crowded growth at the top.
- Flowering and boll set drop sharply; bolls that form stay small and open poorly.
- **Whiteflies with waxy white wings rest on the underside of young leaves** and rise in a cloud when the plant is shaken.
- Infected plants stand out as compact dark bunches among taller normal plants.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Hormone herbicide (2,4-D) drift | Cotton leaf curl shows **thickened dark raised veins with cup-shaped leafy enations on the leaf underside**, plus whiteflies. Herbicide drift gives strap-like fan-shaped leaves with parallel veins across a whole block along a wind line. |""",
        matters="**Devastated cotton across north-west India in successive epidemics.** Infected plants never recover, and resistance in released varieties has broken down repeatedly as the virus recombines.",
        nonchem="""- Grow currently resistant varieties; check the season's PAU or state recommendation because resistance breaks down.
- **Rogue out symptomatic plants in the first six weeks.**
- Sow at the recommended time to avoid the peak whitefly window.
- Remove weed hosts, particularly *Xanthium*, *Abutilon* and wild malvaceous weeds, from field and bunds.
- Yellow sticky traps; avoid synthetic pyrethroids, which cause whitefly resurgence.
- Avoid growing cotton next to an old infected crop."""),

    dict(
        f="groundnut-late-leaf-spot", type="Disease", title="Groundnut leaf spot and rust",
        desc="Fungal leaf spots and orange rust pustules that defoliate groundnut from the bottom up, with dried leaves staying attached in rust.",
        tags="groundnut, leaf-spot, rust, tikka, fungal",
        sci="Phaeoisariopsis personata and Puccinia arachidis", crop="groundnut",
        local="टिक्का रोग, tikka rog, रतुआ, ratua", urgency="high",
        sources=src([TNAU_C, EAGRI_C]),
        symptoms="""**Late leaf spot (tikka):**

- **Nearly circular dark brown to black spots on the upper leaf surface**, 1 to 6 mm across.
- On the underside the same spot is **darker and rougher, with the fungal growth visible as a fine dark bloom**.
- Spots carry **little or no yellow halo**, so the spot sits sharply against green tissue.
- Spots merge and the leaflets **yellow, dry and drop**, defoliating the plant from the bottom upward.

**Rust:**

- **Small raised orange to reddish-brown pustules, mostly on the LOWER leaf surface**, that **rupture and shed an orange powder onto the fingers**.
- The matching upper surface shows small chlorotic flecks.
- **Rust-killed leaves dry but stay attached to the plant**, which distinguishes it from leaf spot.
- Heavy attack gives the whole field a rusty brown cast at a low angle.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Early leaf spot | Late leaf spot is **darker, nearly black, with sporulation on the underside and little yellow halo**. Early leaf spot is lighter brown with a distinct yellow halo. |
| Leaf spot vs rust | Rust gives **raised pustules shedding orange powder, and dried leaves stay attached**. Leaf spot drops the leaves. |""",
        matters="Together these two cause the largest yield losses in Indian groundnut. Defoliation before pod fill costs both pod number and kernel size, and the pods left in soil are harder to lift from a defoliated plant.",
        nonchem="""- Grow tolerant varieties and follow the recommended sowing window.
- **Destroy volunteer groundnut plants and crop residue**, which carry the fungi between seasons.
- Rotate with a cereal such as pearl millet or sorghum for at least one season.
- Intercrop with pearl millet to slow spore spread.
- Avoid dense stands and keep row spacing open.
- Apply well-decomposed farmyard manure to maintain plant vigour."""),

    dict(
        f="mustard-aphid", type="Pest", title="Mustard aphid",
        desc="Dense grey-green aphid colonies coating mustard shoots and pods, with honeydew and sooty mould; the top mustard pest in India.",
        tags="mustard, rapeseed, aphid, sucking-pest, insect", sci="Lipaphis erysimi",
        crop="mustard", local="माहू, mahu, चेपा, chepa, tela", urgency="emergency",
        sources=src([("drmr", "https://drmr.icar.gov.in", "ICAR-DRMR Bharatpur mustard aphid forewarning"), PAU]),
        symptoms="""- **Dense colonies of small soft-bodied grey-green aphids packed shoulder to shoulder** on the central shoot, flower racemes and developing pods.
- The colony is so tight that the **shoot looks thickened and coated in a greyish crust**.
- Each insect carries a **fine greyish-white mealy waxy dusting**, so the colony looks powdered with ash.
- Affected shoots and racemes are **wet, shiny and sticky with honeydew**, and dust sticks to the film.
- A **black sooty mould film** develops on the sticky surfaces and rubs off as black powder.
- **Flowers shed and pods stay short, curved and poorly filled**.
- Growing tips curl, twist and stunt, and the raceme bends over.
- Ants patrol the stems and **white cast skins** of moulted aphids litter the colony.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Painted bug damage | Aphids form **dense immobile grey-green waxy colonies with honeydew, sooty mould and white cast skins**. Painted bugs are larger, brightly marked black and orange, and move actively. |""",
        matters="**The single biggest mustard pest in India.** Peak build-up coincides with flowering and pod fill, when the crop can least afford it. ICAR-DRMR runs a forewarning system for exactly this reason.",
        nonchem="""- **Sow early**, so flowering finishes before the January aphid peak.
- Monitor from late December and act on the first colonies.
- **Conserve ladybird beetles, syrphid larvae and lacewings**, which frequently control the pest without intervention.
- Clip and destroy the first heavily colonised shoot tips.
- Avoid excess nitrogen, which produces soft aphid-friendly growth.
- Grow tolerant varieties where available."""),

    dict(
        f="chickpea-wilt", type="Disease", title="Chickpea wilt",
        desc="Soil-borne Fusarium wilt collapsing chickpea plants in patches, with black internal streaking when the stem is split.",
        tags="chickpea, chana, wilt, fusarium, soil-borne",
        sci="Fusarium oxysporum f. sp. ciceris", crop="chickpea",
        local="उकठा रोग, ukatha rog, मर रोग, mar rog", urgency="high",
        sources=src([TNAU_C, NIPHM, PAU]),
        symptoms="""- Dead and dying plants appear **in distinct patches within the field**, showing as straw-coloured blotches among healthy green.
- At seedling stage the **whole seedling collapses and lies flat with dull green leaves still attached** and a shrunken shrivelled stem.
- In older plants the **leaf stalks and leaflets droop downward in sequence** until the whole plant hangs.
- Leaves pass through **dull green to yellow to straw colour**, and **the dead leaves stay hanging on the plant**.
- **Splitting the stem lengthwise at and just above the collar reveals dark brown to black discolouration of the internal woody tissue** — the most reliable check.
- **Peeling the bark from the root and lower stem shows black vertical streaks** running up the wood.
- Dark brown to black discolouration is visible on the outside of the stem near the collar.
- Sometimes only the branches on one side wilt, giving a half-dead, half-green plant.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Dry root rot | Wilt shows **black vertical vascular streaking inside the split stem with dead leaves retained on the plant**. Dry root rot leaves the plant straw-coloured and standing with brittle shredded roots packed with minute black sclerotia. |""",
        matters="National loss estimates for chickpea wilt and root rot run 20 to 25 percent, reaching total loss in badly infested fields. The fungus persists in soil for years, so it is a land-management problem.",
        nonchem="""- **Grow wilt-resistant varieties**; several are available for each zone.
- **Follow a long rotation** — six years with sorghum is the TNAU recommendation for endemic fields.
- **Avoid early sowing into warm soil**; high soil temperature at sowing strongly favours wilt.
- Seed treatment with a talc formulation of *Trichoderma viride* or *Pseudomonas fluorescens*.
- Soil application of the same bioagents with well-decomposed farmyard manure about 30 days after sowing.
- Rogue and remove wilted plants with their root ball."""),

    dict(
        f="pigeonpea-sterility-mosaic", type="Disease", title="Pigeon pea sterility mosaic",
        desc="Mite-borne virus giving a bushy stunted pigeon pea plant that stays lush and green but sets no pods; known as green plague.",
        tags="pigeonpea, arhar, tur, virus, sterility-mosaic, mite-borne",
        sci="Pigeonpea sterility mosaic virus", crop="pigeon pea",
        local="बांझपन मोज़ेक, banjhpan mosaic, वांझ रोग", urgency="high",
        sources=src([TNAU_C, NIPHM]),
        symptoms="""- The plant is **markedly bushy and stunted with shortened internodes**, so it looks squat and crowded beside its neighbours.
- **Axillary buds sprout profusely and branches crowd together at the top**, producing a dense broom-like head of shoots.
- **Leaves become small and crinkled and cluster tightly near the branch tips**, leaving the lower stem bare.
- Younger leaves show a **light and dark green mosaic pattern**, a pale patchwork across the blade.
- Some plants show **ring spots — a green island ringed by a chlorotic halo**.
- **Diseased plants stay pale green, lush and leafy with very few or no flowers and pods**, while healthy neighbours are loaded. This is why it is called the green plague.
- **Diseased plants occur in clusters** rather than singly, spreading outward from a focus.
- A plant infected after 45 days may show symptoms on only some branches while the rest look normal.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Yellow mosaic on pigeon pea | Sterility mosaic produces a **bushy stunted plant with small crinkled leaves crowded at the branch tips and pale green mosaic, with flowering largely stopped**. |""",
        matters="An infected plant flowers little or never, so it costs the whole plant's yield while still looking healthy and green. That deceptive appearance is why farmers often miss it until harvest.",
        nonchem="""- **Rogue out and destroy infected plants within 40 to 45 days of sowing** — the single highest-value action.
- Grow resistant varieties.
- **Remove perennial and volunteer pigeon pea plants and destroy ratooned regrowth**, which are the reservoir for both mite and virus.
- Keep no standing arhar plants around other fields during winter; these seed the next crop.
- Avoid heavy shade and excessive humidity, which encourage the mite vector."""),

    dict(
        f="greengram-yellow-mosaic", type="Disease", title="Mungbean yellow mosaic",
        desc="Whitefly-borne begomovirus scattering bright yellow patches across green gram and black gram leaves; the top pulse constraint in India.",
        tags="green gram, moong, black gram, urad, virus, yellow-mosaic, whitefly-borne",
        sci="Mungbean yellow mosaic virus", crop="green gram",
        local="पीला चितकबरा रोग, peela chitkabra rog, पीत शिरा मोज़ेक", urgency="high",
        sources=src([TNAU_C, PAU, ("cabi-mymv", "https://plantwiseplusknowledgebank.org/doi/full/10.1079/pwkb.20157801443",
                                   "CABI Plantwise factsheet mungbean yellow mosaic virus")]),
        symptoms="""- **Small irregular yellow patches scattered at random over the green leaf blade**, and the patches **cross over the veins** rather than being bounded by them.
- Patches **enlarge and merge until the leaf shows broad bright yellow blotches alternating with islands of remaining green** — a strong two-colour mosaic.
- **Whole leaves finally go completely bright yellow**, so one plant carries fully yellow, mosaic and green leaves at once.
- **New leaves at the growing tip emerge entirely yellow and undersized.**
- Affected leaves are **cupped downward, wrinkled and puckered**.
- **Internodes shorten and the plant is severely stunted**, sitting low among healthy neighbours.
- **Pods turn yellow, stay small, curl and become distorted**, and the plant sets very few.
- Turning a leaf over shows **tiny white insects about 1 mm with waxy white wings that fly up in a cloud**, with flat black oval nymphs sitting motionless on the underside.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Iron or manganese deficiency | Yellow mosaic gives **irregular bright yellow patches that cross the veins in a random scattered mosaic on individual plants, with whiteflies on the leaf undersides**. Deficiency yellows evenly between veins on the newest leaves uniformly across the field. |""",
        matters="**The single biggest constraint to moong and urad productivity in India.** The earlier a plant is infected the greater the loss, and summer-sown crops in endemic areas are highly susceptible.",
        nonchem="""- **Grow resistant or tolerant varieties**; several are released for each zone.
- **Rogue out diseased plants early**, as soon as the first yellow patches appear.
- **Avoid summer-sown crops in endemic areas.**
- Remove weed reservoir hosts — *Croton sparsiflorus*, *Acalypha indica*, *Eclipta alba* — from field and bunds.
- Yellow sticky traps to monitor and trap whitefly adults.
- Avoid sowing next to a mature infected crop."""),

    dict(
        f="soybean-yellow-mosaic", type="Disease", title="Soybean yellow mosaic",
        desc="Whitefly-borne virus mottling soybean leaves yellow and green with puckering and severe stunting.",
        tags="soybean, virus, yellow-mosaic, begomovirus, whitefly-borne",
        sci="Mungbean yellow mosaic India virus", crop="soybean",
        local="पीला मोज़ेक, peela mosaic", urgency="high",
        sources=src([TNAU_C, ("iisr-indore", "https://iisrindore.icar.gov.in",
                              "ICAR-Indian Institute of Soybean Research Indore")]),
        symptoms="""- **Bright yellow patches scattered irregularly over the green leaf**, crossing freely over the veins.
- Patches enlarge until the leaf shows **bold yellow and green mottling**, and whole leaflets may go golden yellow.
- Leaflets are **puckered, cupped downward and uneven** in surface.
- **New trifoliate leaves emerge yellow, small and misshapen.**
- **Internodes shorten and the plant is stunted and bushy.**
- **Pods are few, small, pale and poorly filled**, and rattle because the seeds inside are shrivelled.
- Seeds from infected plants are small and mottled.
- **Whiteflies with waxy white wings rise from the canopy when plants are shaken**, and flat oval nymphs sit on leaf undersides.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Iron deficiency chlorosis | Yellow mosaic gives **sharply bounded irregular yellow blocks alternating with fully normal green tissue on the same leaf, with whiteflies present**. Deficiency yellows evenly between the veins on the newest leaves across the whole field. |""",
        matters="Losses run 5 to 100 percent depending on infection timing. Because soybean is grown as a block crop across Madhya Pradesh and Maharashtra, whitefly-driven spread can move through a district quickly.",
        nonchem="""- **Grow resistant or tolerant varieties.**
- Rogue out symptomatic plants early and destroy them.
- Adjust sowing date to avoid the whitefly peak.
- Yellow sticky traps through the crop.
- Sow tall barrier rows of maize, sorghum or bajra around the plot.
- Keep leguminous weeds and volunteer pulses cleared, and avoid overlapping pulse crops that bridge whitefly generations."""),

    dict(
        f="wheat-loose-smut", type="Disease", title="Wheat and barley loose smut",
        desc="Seed-borne smut replacing every grain in the ear with dry black powder that blows away leaving a bare stalk.",
        tags="wheat, barley, smut, fungal, seed-borne", sci="Ustilago nuda", crop="wheat",
        local="कंडुआ, kandua, खुला कंडुआ, कांगियारी", urgency="moderate",
        sources=src([PAU, ("iiwbr-smut", "https://iiwbr.icar.gov.in/crop-protection/",
                           "ICAR-IIWBR crop protection")]),
        symptoms="""- The affected ear **emerges earlier than the healthy ears around it**, so it stands out at heading.
- **Every grain position in the ear is replaced by a mass of dry dark brown to black powder.**
- The powder is held only briefly by a **very thin fragile skin, which soon breaks and lets the spores blow away on the wind**.
- What remains is a **bare stripped central stalk standing naked** with a few remnants.
- Walking through an infected patch **raises a visible cloud of dark dust** and leaves black powder on clothing.
- Smutted heads stand out from a distance as **black brush-like ears among clean green ears**.
- Every ear on a diseased plant is affected, because the plant was infected as seed.
- Healthy neighbouring plants stay entirely clean, so the pattern is scattered individuals rather than patches.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Covered smut | Loose smut **leaves a bare rachis after the powder blows off**. Covered smut keeps a firm grey-white membrane over a solid black mass with the awns still standing. |
| Ergot | Ergot leaves the ear shape intact and produces sticky droplets, then hard black horn-shaped bodies protruding beyond the glumes. |""",
        matters="Nothing can be done in the standing crop; the outcome was fixed when the seed was sown. That makes it purely a **seed-quality problem**, and it is entirely preventable.",
        nonchem="""- **Use certified, disease-free seed from a healthy seed plot.** The fungus lives inside the embryo.
- **Solar seed treatment**: soak seed in water for a few hours, then spread it in strong midday sun on a hot summer day to kill the dormant mycelium inside the embryo. A long-standing PAU and IIWBR recommendation.
- **Rogue smutted heads before the spore mass breaks open** — bag the head, cut it, and destroy it away from the field.
- Keep clean seed lots physically separated from smutted grain at threshing."""),
]

if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bundle", "diseases")
    write_all(CONCEPTS, os.path.normpath(out))
