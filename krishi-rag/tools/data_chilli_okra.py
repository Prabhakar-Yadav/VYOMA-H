# -*- coding: utf-8 -*-
"""Chilli and okra concepts. Sources: TNAU, eagri PATH-371/ENTO-331, ICAR-NBAIR, CABI."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_concepts import EAGRI, TNAU, src, write_all

NBAIR = ("nbair", "https://www.nbair.res.in/sites/default/files/2021-12/Pest%20alert_F.pdf",
         "ICAR-NBAIR pest alert on Thrips parvispinus")

CONCEPTS = [
    dict(
        f="chilli-anthracnose", type="Disease", title="Chilli anthracnose and die-back",
        desc="Fungal fruit rot and twig die-back producing sunken pits with rings of black dots and pink slime on chilli fruit.",
        tags="chilli, anthracnose, dieback, fungal, fruit-rot", sci="Colletotrichum capsici",
        crop="chilli", local="फल सड़न, phal sadan, अग्रमारी, agramari, bokadya", urgency="high",
        sources=src([TNAU, EAGRI,
                     ("pmc-anth", "https://pmc.ncbi.nlm.nih.gov/articles/PMC5044472/",
                      "Chilli anthracnose epidemiology and management")]),
        symptoms="""- On fruit: circular to oval **sunken pits**, the skin dented inward like a thumb press, most abundant on red ripening fruit.
- Inside each pit sit **rings of tiny black dots arranged in concentric circles**, like fine black pepper laid out in a target pattern.
- In humid weather the pit centre carries a **wet pink to salmon-orange slime** that smears when rubbed with a finger.
- Old dried lesions turn straw-white to bleached grey; the fruit becomes papery, shrivelled and light in the hand.
- On twigs the growing tip dies first and browning creeps **downward from the tip toward the base** — the classic die-back stick.
- Flowers and flower stalks shrivel, dry and drop in large numbers, leaving bare flower scars along the branch.
- On stems near soil, dead brown patches are edged by a **sharp dark brown to black band** separating dead from green tissue.
- Whole plant: partially bare twiggy branches carrying a few small, poor-quality fruit.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Bacterial leaf and fruit spot | Bacterial spots stay small, raised, rough and scabby with a pale yellow rim. Anthracnose pits carry concentric rings of black dots plus pink slime. |""",
        matters="Fruit losses compound with every rain event. A whole marketable crop can be lost inside two to three weeks in a wet spell.",
        nonchem="""- Sow only seed saved from clean, healthy fruit; the seed carries the fungus.
- Pick and bury or burn every rotting fruit **daily** during the ripening flush. The pink slime is the source of new infections spread by rain splash.
- Harvest ripe fruit promptly rather than leaving red fruit hanging.
- Dry harvested chilli on raised racks or clean sheets, keeping fruit off bare soil.
- Destroy old crop twigs and stakes after harvest; the fungus survives on dry dead twigs.
- Space rows for wind drying and avoid working the crop while foliage is wet."""),

    dict(
        f="chilli-thrips", type="Pest", title="Chilli thrips upward leaf curl",
        desc="Sap-sucking thrips causing upward leaf cupping, a silvery bronzed leaf surface and elongated leaf stalks in chilli.",
        tags="chilli, thrips, murda, sucking-pest, insect", sci="Scirtothrips dorsalis",
        crop="chilli", local="थ्रिप्स, thrips, मुरड़ा, murda, tamara", urgency="high",
        sources=src([TNAU, EAGRI]),
        symptoms="""- Leaf margins curl **upward**, so the leaf becomes a boat or cup opening toward the sky.
- Leaf surface is crinkled and puckered, the blade reduced, and the **leaf stalk noticeably elongated**.
- Upper leaf surface shows a dull **silvery-grey to bronze sheen** where the green has been rasped away.
- Along the midrib and veins on the underside there are fine **brown scratchy streaks and dark specks of insect droppings**.
- Insects are extremely slender **straw-yellow slivers about 1 mm long**, moving briskly, sheltering deep in the folded leaf tip and inside flowers.
- Flower buds feel brittle and snap off; the ground under the plant carries dropped buds.
- Whole plant looks stunted and bronzed, with the top cluster of leaves bunched and erect.
- Damaged growing points give the shoot tip a tufted, congested look.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Yellow mite damage | Mite curls the leaf **downward** with a glossy coppery underside. Thrips curls it **upward** into a cup. |
| Chilli leaf curl virus | Virus makes leaves thick and leathery with swollen raised yellow veins and very short internodes. |""",
        matters="Peaks in hot dry weather. Farmers call the whole leaf-curl group *murda*, so a farmer saying murda may mean thrips, mite or virus. These are three different problems needing three different actions.",
        nonchem="""- Sprinkle or overhead-water seedlings in the nursery; free water on leaves suppresses thrips multiplication.
- Intercrop or border with tall agathi (*Sesbania grandiflora*) to moderate build-up.
- Install **sky-blue sticky traps** through the crop; blue attracts thrips more strongly than yellow.
- Avoid sorghum as the preceding crop and keep chilli and onion in separate blocks; both host thrips.
- Remove and destroy heavily curled shoot tips early.
- Conserve predatory thrips and lacewings by avoiding broad-spectrum sprays."""),

    dict(
        f="chilli-yellow-mite", type="Pest", title="Chilli yellow mite downward leaf curl",
        desc="Broad mite causing downward leaf curl, glossy coppery leaf undersides and the distinctive rat-tail leaf stalk in chilli.",
        tags="chilli, mite, murda, broad-mite", sci="Polyphagotarsonemus latus",
        crop="chilli", local="पीला माइट, peela mite, मुरड़ा, murda, muranai", urgency="high",
        sources=src([EAGRI,
                     ("phyto", "https://link.springer.com/article/10.1007/s12600-024-01164-4",
                      "Morphological basis of resistance to yellow mite and thrips in chilli")]),
        symptoms="""- Leaf margins curl **downward**, so the leaf becomes an inverted boat, narrow and strap-like.
- Leaf underside turns **glossy, hard and coppery-brown**, with a varnished or leathery texture.
- Leaf blade shrinks and the surface carries **raised blister-like patches** between the veins.
- The leaf stalk stretches out very long while the blade stays tiny — the classic **rat-tail symptom**, leaves like thin whips.
- The whole shoot tip stops growing, stays bunched and dark green, and finally dries.
- The mite is invisible to the unaided eye at 0.1 to 0.2 mm. A hand lens shows translucent yellowish-green oval specks packed on the **underside of the youngest leaves and inside leaf buds**.
- Damage concentrates on the **top third of the plant** while older lower leaves stay broad and flat.
- Fruit set from affected tips is sparse and the fruit surface can be russeted and corky.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Chilli thrips damage | Thrips curls the leaf **upward** into a cup with a silvery bronzed top. Mite curls it **downward** with a glossy coppery underside and a long rat-tail stalk. |""",
        matters="The growing point can be killed outright, ending that plant's productive life. Damage is always on the youngest tissue, so scouting old leaves misses it entirely.",
        nonchem="""- Scout the **top three leaves** weekly with a hand lens; mites are found only on the youngest tissue.
- Pinch out and destroy affected growing tips as soon as downward curling appears, carrying them out of the field in a closed bag.
- Keep the crop well watered; hot dry stress accelerates mite build-up.
- Rogue out severely stunted rat-tail plants that have stopped producing.
- Wash hands and tools after handling infested plants; mites travel on clothing and on whiteflies.
- Conserve predatory mites such as *Amblyseius* by avoiding broad-spectrum sprays."""),

    dict(
        f="chilli-leaf-curl-virus", type="Disease", title="Chilli leaf curl virus",
        desc="Whitefly-borne begomovirus causing thick leathery leaves with swollen yellow veins and severe stunting in chilli.",
        tags="chilli, virus, leaf-curl, begomovirus, whitefly-borne", sci="Chilli leaf curl virus",
        crop="chilli", local="पत्ती मरोड़ रोग, patti marod rog, मुरड़ा, murda", urgency="high",
        sources=src([TNAU,
                     ("pmc-chilcv", "https://pmc.ncbi.nlm.nih.gov/articles/PMC9277185/",
                      "An overview of chilli leaf curl disease in the Indian subcontinent")]),
        symptoms="""- Leaf margins roll **upward and inward** and the whole blade puckers into a crinkled, blistered sheet.
- Leaves are markedly **smaller and thicker** than healthy leaves, with a hardened crisp feel.
- Veins stand out **swollen, raised and pale yellow**, giving a prominent vein-banding pattern.
- Leaf stalks and stem internodes shorten drastically, so leaves stack into a **dense bunched rosette** at the shoot tip.
- Whole plant is severely stunted and bushy, throwing out many short side branches.
- Flower buds drop before opening.
- Small clouds of **tiny white moth-like insects about 1.5 mm with waxy white wings** fly up when the plant is disturbed; they rest on the leaf underside.
- Affected plants stand out as compact dark bunches among taller normal plants, visible even in a wide field photo.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Thrips leaf curl | Virus gives **thickened leathery leaves with swollen raised yellow veins and very short internodes**, plus whiteflies on the underside. |""",
        matters="Infected plants **never recover**. Early infection ends that plant's yield entirely, and the plant remains a source of infection for the rest of the field.",
        nonchem="""- Raise the nursery under a fine insect-proof net so seedlings enter the field virus-free.
- Uproot and destroy symptomatic plants as soon as they appear, especially in the first month.
- Plant two to three border rows of tall maize or sorghum as a physical barrier to incoming whiteflies.
- Hang yellow sticky traps through the crop.
- Keep field and bunds free of weed hosts that carry begomoviruses between crops.
- Avoid planting new chilli next to an old infected chilli or tomato crop."""),

    dict(
        f="chilli-black-thrips", type="Pest", title="Chilli black thrips",
        desc="Invasive dark thrips swarming inside chilli flowers and causing mass flower drop; epidemic in south India since 2021.",
        tags="chilli, thrips, invasive, flower-drop, insect", sci="Thrips parvispinus",
        crop="chilli", local="काला थ्रिप्स, kala thrips, nalla tamara", urgency="emergency",
        sources=src([NBAIR,
                     ("cursci", "https://www.currentscience.ac.in/Volumes/122/02/0211.pdf",
                      "Rachana et al, Current Science 122(2) 2022")]),
        symptoms="""- Adults are **dark brown to near-black with contrasting pale yellow legs**, roughly 1 mm long. They read as dark specks.
- The head and thorax appear brighter than the darker abdomen; forewings are brown with a pale patch at the base.
- Insects **swarm inside open flowers in large numbers**, commonly 15 to 20 per flower. Tipping a flower over a white cloth makes them fall out and run.
- Massive flower shedding: the soil under the plant is **carpeted with dropped flowers and buds**.
- Tender leaves and shoot tips show a **silvery-grey wash turning brown**, with crinkling and upward curling.
- Buds and leaves feel dry and brittle and snap off when touched.
- Fruit that does set is **malformed, twisted and scarred with brown corky patches**, and drops early.
- Field view: flowering plants standing green but almost fruitless, with heavy petal fall.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Native chilli thrips (*S. dorsalis*) | *T. parvispinus* adults are **dark brown or black with yellow legs and congregate inside flowers causing mass flower drop**. *S. dorsalis* is pale straw-yellow and works mainly on leaf tips. |""",
        matters="**Invasive and spreading.** Ninety to ninety-five percent of flowers can be damaged. Growers in Andhra Pradesh, Chhattisgarh and Karnataka abandoned entire crops in the 2021 to 2022 outbreaks. Current distribution is wider than published surveys record.",
        nonchem="""- Use only healthy pest-free seedlings and inspect flowers of neighbouring plots before planting.
- Monitor by **tapping flowering shoots over a white tray** and counting the dark thrips that fall.
- Destroy heavily infested plants completely in newly affected areas to stop local spread.
- Apply neem oil, pongamia oil or soap solution **directed into flowers and fruit clusters**, where the insect actually sits.
- Remove and destroy dropped flowers and buds from the plot floor.
- Avoid repeated broad-spectrum insecticides; resistance and natural-enemy loss were central to the outbreaks."""),

    dict(
        f="okra-yellow-vein-mosaic", type="Disease", title="Okra yellow vein mosaic",
        desc="Whitefly-borne begomovirus turning the okra vein network bright yellow and producing pale ivory-white pods.",
        tags="okra, bhindi, virus, mosaic, begomovirus, whitefly-borne",
        sci="Bhendi yellow vein mosaic virus",
        crop="okra", local="पीली शिरा मोज़ेक, peeli sira mosaic, manjal naramburogam", urgency="high",
        sources=src([("tnau-okra", "https://agritech.tnau.ac.in/crop_protection/bhendi_diseases_4.html",
                      "TNAU bhendi yellow vein mosaic"),
                     ("cabi-okra", "https://plantwiseplusknowledgebank.org/doi/10.1079/PWKB.20157800445",
                      "CABI Plantwise vein clearing of okra")]),
        symptoms="""- The **entire vein network glows yellow** while the tissue between the veins stays green — a bright yellow net drawn on a green leaf.
- As it advances the pattern reverses: areas between veins turn **completely yellow or chalk-white**, and finally the whole blade goes uniformly yellow.
- Young leaves are undersized and the plant becomes visibly short and bunched.
- Held up against the sun, the veins and veinlets **shine translucent and clear**.
- **Fruits turn pale yellow to ivory-white** instead of green — a striking and unmistakable photo cue.
- Affected pods are small, straight, hard and woody to the touch.
- Flowering is sparse and pod set drops sharply.
- Small white moth-like whiteflies rest on the underside of the youngest leaves and fly up in a cloud when the plant is shaken.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Okra enation leaf curl virus | Enation produces **pin-head warty bumps on the leaf underside** with thick leathery curled leaves and twisted stems. Yellow vein mosaic keeps leaves flat and turns fruit ivory-white. |""",
        matters="Early infection can take the entire yield, and infection occurs at any growth stage. Losses are heaviest in the summer crop when whitefly numbers peak.",
        nonchem="""- Grow tolerant varieties — Parbhani Kranti, Arka Anamika, Arka Abhay, Varsha Uphar, Janardhan, Haritha.
- Avoid susceptible varieties in the summer crop.
- Uproot and destroy diseased plants as soon as the yellow vein pattern shows, from the seedling stage onward.
- Hang yellow sticky traps to intercept whitefly adults.
- Keep bunds clear of malvaceous weeds such as *Abutilon indicum* and wild hibiscus that host the virus.
- Avoid synthetic pyrethroids, which are documented to worsen whitefly numbers and aggravate this disease."""),

    dict(
        f="okra-shoot-fruit-borer", type="Pest", title="Okra shoot and fruit borer",
        desc="Caterpillar that kills okra shoot tips then bores frass-plugged holes into pods; up to 70 percent pod loss.",
        tags="okra, bhindi, borer, caterpillar, insect", sci="Earias vittella",
        crop="okra", local="तना एवं फल छेदक, tana evam phal chhedak, phal chhedak", urgency="high",
        sources=src([EAGRI,
                     ("nhb-okra", "https://nhb.gov.in/pdf/vegetable/okra/okr007.pdf",
                      "National Horticulture Board okra pest factsheet")]),
        symptoms="""- Before flowering the **terminal shoot droops, wilts and hangs limp**, then dries brown while the rest of the plant stays green — a dead-heart flag visible from a distance.
- A single **round bore hole** sits on the drooping shoot, usually a few centimetres below the tip.
- The hole is **plugged with wet brown-black granular excreta** pushed outward, often sitting like a small mound at the entrance.
- On pods: one or more circular entry holes on the side or near the stalk end, again ringed with frass.
- Cut pods reveal a hollowed tunnel packed with dark frass and a soft caterpillar feeding on the seeds.
- Damaged pods are **bent, twisted and lumpy**, losing their straight ridged form.
- The caterpillar is brown with **whitish longitudinal stripes down the back** and raised warts.
- The adult moth rests with a **broad wedge-shaped pea-green patch across the middle of pale white forewings**.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| *Helicoverpa* fruit borer | *Earias* kills the **growing shoot tip first**, producing drooping dead terminal shoots. That symptom is unique to this pest in okra. |""",
        matters="Up to 70 percent pod loss, and damage makes pods unsaleable immediately. Because the caterpillar feeds inside, clipping bored shoots is more reliable than spraying.",
        nonchem="""- Walk the field every two to three days and **clip off drooping shoots and bore-holed pods**, then bury or burn them. This alone drives populations down sharply.
- Harvest pods young and frequently, denying larvae time to complete development inside the fruit.
- Remove alternate malvaceous hosts around the field: *Hibiscus cannabinus*, *Abutilon indicum*.
- Set pheromone traps for *Earias* at about five per hectare, plus light traps.
- Grow tolerant cultivars where available (AE 57, PMS 8, Parbhani Kranti group).
- Uproot and destroy crop stubble immediately after final harvest to break carry-over."""),

    dict(
        f="okra-jassid", type="Pest", title="Okra jassid hopper burn",
        desc="Leafhopper causing yellow then rusty-brown scorched leaf margins that cup upward, working from the lower leaves up.",
        tags="okra, bhindi, jassid, leafhopper, sucking-pest", sci="Amrasca biguttula biguttula",
        crop="okra", local="हरा तेला, hara tela, फुदका, phudka, tudtude", urgency="high",
        sources=src([EAGRI,
                     ("cabi-jassid", "https://www.cabidigitallibrary.org/doi/10.1079/cabicompendium.20857",
                      "CABI Compendium Amrasca biguttula")]),
        symptoms="""- Leaf **margins turn yellow first**, in a band following the rim of the leaf all the way round.
- The yellow band then goes **rusty-red to bronze, and finally dry brown and crisp** — hopper burn, reading as a scorched border on a green leaf.
- Leaf margins **curl upward**, cupping the leaf, with a crinkled puckered surface.
- Damage moves **from the older lower leaves upward**, so the bottom of the plant looks burnt while the top stays green.
- On the underside, tiny **wedge-shaped pale-green insects** about two to three mm sit along the veins, broad at the head and tapering to the rear.
- Nymphs are wingless, pale greenish-white, and **run sideways or diagonally** when disturbed — a very distinctive movement cue.
- Adults hop or fly off instantly when the leaf is turned over.
- Severely hit plants stay short and stunted with a bronzed, dried-out lower canopy.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Potassium deficiency | Jassid damage comes with **live wedge-shaped green hoppers and pale nymphs that scuttle sideways on the leaf underside**. Deficiency has no insects present. |""",
        matters="Can cut yield and quality by up to 50 percent. Because the insects sit only on the underside, a farmer inspecting leaf tops will miss them entirely.",
        nonchem="""- Turn over lower leaves at every field visit; the insects live only on the underside.
- Grow **hairy or pubescent-leaved okra varieties**, which are markedly less preferred by jassids.
- Set yellow sticky traps to catch adults and track build-up.
- Avoid synthetic pyrethroids, which cause jassid and whitefly resurgence.
- Conserve spiders, lacewings and mirid bugs by restraining broad-spectrum sprays.
- Remove crop residue and volunteer okra or cotton after harvest."""),
]

if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bundle", "diseases")
    write_all(CONCEPTS, os.path.normpath(out))
