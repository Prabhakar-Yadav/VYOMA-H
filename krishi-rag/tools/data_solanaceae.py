# -*- coding: utf-8 -*-
"""Additional tomato, potato, onion and brinjal concepts.

Sources: TNAU eagri PATH-371 / ENTO-331, ICAR, Cornell, UC IPM, peer-reviewed.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_concepts import EAGRI, TNAU, src, write_all

CONCEPTS = [
    # ---------------- TOMATO ----------------
    dict(
        f="tomato-leaf-curl-virus", type="Disease", title="Tomato leaf curl virus",
        desc="Whitefly-borne begomovirus giving thick leathery downward-curled leaves, short internodes and a bushy broom-shaped tomato plant.",
        tags="tomato, virus, leaf-curl, begomovirus, whitefly-borne",
        sci="Tomato leaf curl virus", crop="tomato",
        local="पत्ती मरोड़ रोग, patti marod rog, churda murda", urgency="high",
        sources=src([EAGRI, TNAU]),
        symptoms="""- Leaflets roll **downward and inward**, curling under toward the leaf stalk, with crinkled margins.
- Newly emerging leaves carry a **light yellow wash along the margins** before they curl.
- Older affected leaves become **thick, leathery and brittle**, snapping rather than bending when folded.
- Stem internodes and leaf stalks shorten sharply, compressing the plant.
- The plant throws out **many short lateral branches, giving a dense bushy broom-like shape**.
- Whole plant is severely stunted and pale, standing well below healthy neighbours.
- Flowering continues but fruit set is sparse and fruits stay small.
- **Whiteflies about 1.5 mm with waxy white wings** rest on the underside of young leaves and rise in a cloud when the plant is shaken.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Hormone herbicide (2,4-D) drift | The virus gives **thick leathery brittle leaves, short internodes and a bushy broom habit with whiteflies underneath**. Herbicide drift gives thin strap-like fan-shaped leaves with parallel veins and affects a whole block uniformly along a wind line. |""",
        matters="Infected plants never recover. Infection in the first month costs essentially the whole plant's yield, and the plant then feeds the virus to the rest of the field.",
        nonchem="""- Raise the nursery under fine insect-proof net.
- Rogue out symptomatic plants in the first 30 to 40 days.
- Hang yellow sticky traps through the crop.
- Sow two to three border rows of maize or sorghum as a barrier.
- Use silver or reflective plastic mulch, which repels whiteflies.
- Clear solanaceous weeds and avoid planting new tomato beside an old infected tomato or chilli crop."""),

    dict(
        f="tomato-bacterial-wilt", type="Disease", title="Tomato bacterial wilt",
        desc="Soil-borne bacterial wilt that collapses a fully green tomato plant within days; confirmed by a milky stream from a cut stem in water.",
        tags="tomato, brinjal, bacterial, wilt, soil-borne, emergency",
        sci="Ralstonia solanacearum", crop="tomato",
        local="जीवाणु उकठा रोग, jeevanu ukhta, murjhan", urgency="emergency",
        sources=src([EAGRI, TNAU]),
        symptoms="""- A **fully green, healthy-looking plant wilts suddenly and completely** while its leaves stay green.
- The plant **wilts in the midday heat and stands back up by the following morning**, repeating for two to three days before collapsing permanently.
- The lowest leaves may droop first, then the whole plant flops over.
- Cutting the stem near the base crosswise shows a **brown to dark discoloured ring** where the water-conducting tissue runs.
- **Suspending the cut stem in a glass of clear water releases a milky-white thread that streams downward from the cut end like smoke.** This is the decisive field test.
- Squeezing the cut stem produces a sticky greyish-white ooze on the cut face.
- Wilted plants appear in **patches following irrigation water flow and along the row**.
- Roots and the lower stem darken and can be soft and water-soaked.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Fusarium wilt | Bacterial wilt keeps the **leaves fully green** on a collapsed plant and gives a **milky white bacterial stream in clear water**. Fusarium yellows the lower leaves progressively, often on one side, and its sap stays clear. |""",
        matters="Plants die within days of the first wilt. The bacterium survives in soil for years and travels in irrigation water, so a single infected patch can seed a whole field.",
        nonchem="""- Rotate with documented suppressive sequences: cowpea to maize to cabbage, or finger millet to brinjal.
- Graft onto resistant rootstock where available.
- Avoid injuring roots during transplanting and weeding.
- **Control root-knot nematodes**, which sharply increase wilt incidence.
- Plant on raised beds with sharp drainage, and direct irrigation so water does not run from infected patches to clean ones.
- Rogue out wilted plants together with the surrounding soil ball and destroy them."""),

    dict(
        f="tomato-pinworm-tuta", type="Pest", title="Tomato pinworm",
        desc="Invasive leaf-mining moth making broad blotch mines packed with black frass and pinholes under the tomato calyx; 80 to 100 percent loss where uncontrolled.",
        tags="tomato, tuta, pinworm, leafminer, invasive, insect",
        sci="Phthorimaea absoluta", crop="tomato",
        local="टमाटर पिनवर्म, tamatar pinworm, टूटा, tuta", urgency="emergency",
        sources=src([("icar-tuta", "https://icar.gov.in/node/7571",
                      "ICAR Tuta absoluta invasive pest alert"), EAGRI]),
        symptoms="""- Leaves carry **large irregular blotch-shaped mines — broad translucent windows** rather than thin winding lines.
- Fresh mines look like **pale silvery-white papery patches**; held to the light they show a hollow chamber with a caterpillar inside.
- Older mines **turn brown and necrotic** and the whole leaf appears scorched and dried.
- Inside each mine sits a **dark thread or granular pile of black excreta**, clearly visible through the transparent leaf skin.
- On fruit: **small round pinhole entry holes, most often under or beside the green calyx crown**.
- The pinhole is **rimmed with black frass**; cutting the fruit reveals winding galleries packed with excreta and a caterpillar.
- The caterpillar is small, up to about 9 mm, **cream to green with a black head and a dark band just behind the head**.
- Stems and growing tips carry bored galleries, causing tips to wilt and the plant to become deformed.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Serpentine leaf miner (*Liriomyza*) | Pinworm makes **broad blotch mines containing black frass**. *Liriomyza* makes thin winding snake-like trails and leaves fruit clean. |
| *Helicoverpa* fruit borer | *Helicoverpa* makes one large hole with a big caterpillar hanging half out. Pinworm makes tiny frass-rimmed pinholes hiding a small larva under the calyx. |""",
        matters="**Invasive**, first recorded at Pune in October 2014 and now across the country. Losses reach 80 to 100 percent where uncontrolled, and it moves between districts on seedlings and fruit crates.",
        nonchem="""- Install **pheromone water traps at about 25 per hectare for mass trapping** and four to five per hectare for monitoring.
- Raise seedlings under insect-proof net and inspect before transplanting.
- Remove and destroy all mined leaves, bored fruits and crop residue in a closed bag or deep pit.
- Deep-plough and solarise between crops to kill soil pupae.
- Observe a host-free period between tomato crops.
- Avoid moving seedlings and fruit crates between infested and clean districts."""),

    dict(
        f="tomato-fruit-borer", type="Pest", title="Tomato fruit borer",
        desc="Large caterpillar boring a clean round hole in tomato fruit with its body hanging outside; damages several fruits in sequence.",
        tags="tomato, chickpea, borer, caterpillar, helicoverpa, insect",
        sci="Helicoverpa armigera", crop="tomato",
        local="फल छेदक, phal chhedak, अमेरिकन सूंडी, american sundi", urgency="high",
        sources=src([EAGRI, TNAU]),
        symptoms="""- A **large clean circular hole** in the fruit, typically near the stalk end, with neat unfrayed edges.
- The classic sight: **the caterpillar's head and front half buried inside the fruit while the rear half hangs outside** in the open.
- Wet dark frass accumulates around the entry hole and drips down the fruit.
- Cut fruit shows a large hollow cavity with the flesh eaten out, often partly water-filled.
- Bored fruits ripen early, turn a patchy off-colour, rot and drop.
- Caterpillars vary widely in colour — green, pink, brown or nearly black — always with **fine pale longitudinal lines down the body and scattered dark bristly warts**.
- Young larvae first scrape leaves and eat flower buds before moving to fruit.
- One caterpillar damages several fruits in sequence, so damage is scattered across the plant.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Tomato pinworm | *Helicoverpa* makes **one large hole with a big caterpillar visibly hanging half out**. Pinworm makes tiny frass-rimmed pinholes under the calyx with a small larva inside. |""",
        matters="One caterpillar spoils several fruits rather than one, so damage runs ahead of the visible larval count. Also a major pest of chickpea and cotton.",
        nonchem="""- Hand-pick caterpillars and destroy bored fruits at every harvest round.
- Install pheromone traps and light traps.
- **Grow American tall marigold as a trap crop** — 40-day-old marigold with 25-day-old tomato seedlings at a 1:10 row ratio — and destroy marigold heads carrying eggs.
- Release *Trichogramma* egg parasitoids.
- Apply *Bacillus thuringiensis* or neem seed kernel extract.
- Deep summer ploughing to expose pupae, and erect bird perches in the field."""),

    # ---------------- POTATO ----------------
    dict(
        f="potato-early-blight", type="Disease", title="Potato early blight",
        desc="Fungal leaf spot producing dry brown target-ringed spots on the oldest potato leaves, climbing steadily up the plant.",
        tags="potato, blight, fungal, alternaria", sci="Alternaria solani", crop="potato",
        local="अगेती झुलसा, ageti jhulsa", urgency="moderate",
        sources=src([EAGRI]),
        symptoms="""- **Brown-black angular to oval dead spots** appear first on the **oldest, lowest leaves**.
- Each spot carries **distinct concentric rings inside it, like the rings in a cut tree stump or a dartboard**. This is the defining feature.
- Spots are ringed by a **yellow halo** that spreads into the surrounding green tissue.
- Spots stay bounded by leaf veins, giving them an angular blocky shape.
- Spots are **dry and crisp to the touch**, and merge until whole leaflets go brown; dead leaves hang on the stem.
- Damage climbs steadily up the plant from the base while the top stays green.
- Favoured by **warm dry weather broken by intermittent rain**, and hits poorly nourished low-vigour crops hardest.
- Tubers can carry dark, slightly sunken circular surface lesions with a firm dry brown rot beneath.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Potato late blight | Early blight spots are **dry, brown and carry concentric target rings, starting on the oldest bottom leaves in warm weather**. Late blight makes water-soaked greasy dark patches with a white fuzzy ring underneath, spreading fastest in cool wet cloudy weather with a musty smell. |""",
        matters="Progresses over weeks rather than days, so there is usually time to act. Low-vigour, under-fertilised crops are far more severely affected.",
        nonchem="""- Plant certified disease-free seed tubers.
- Maintain strong balanced nutrition; low-vigour crops are far more susceptible.
- Rotate away from solanaceous crops.
- Remove and destroy crop debris, where spores survive 17 months or more.
- Wide spacing and ridge planting; irrigate at the base early in the day.
- Grow tolerant varieties such as Kufri Sindhuri."""),

    dict(
        f="potato-black-scurf", type="Disease", title="Potato black scurf and stem canker",
        desc="Hard black crusts stuck on the potato tuber skin that scrape off to reveal clean skin, plus brown girdling cankers on underground stems.",
        tags="potato, scurf, canker, fungal, rhizoctonia, storage",
        sci="Rhizoctonia solani", crop="potato",
        local="काली खुरंड, kali khurand, black scurf", urgency="moderate",
        sources=src([EAGRI]),
        symptoms="""- The washed tuber skin carries **hard black to dark brown crusty flecks and irregular flat scabs stuck firmly onto the surface**, looking exactly like dried soil clods.
- Scraping with a fingernail **lifts the black flecks away cleanly, revealing perfectly normal healthy white skin underneath**. This is the definitive test.
- Flecks range from pinhead specks to large irregular plaques, sometimes covering much of the tuber.
- The skin between the flecks can show a **rough russeted, netted corky texture**.
- At planting, sprouts from affected seed show **dark brown sunken cankers on the underground stem and stolons**, which can girdle and kill the sprout.
- Emergence is patchy and uneven, with gaps in the row.
- Affected plants may produce a cluster of small aerial tubers in the leaf axils above ground.
- Wilting appears where stem cankers have girdled the stem.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Common scab | Black scurf sits **on top of the skin as removable black crusts leaving clean skin beneath**. Common scab eats into the tuber as raised or pitted rough corky brown lesions that stay fixed. |""",
        matters="Mostly cosmetic on the tuber surface, but it severely downgrades seed and table value, and the stem canker phase causes gappy emergence that costs plant stand.",
        nonchem="""- Plant only clean, scurf-free certified seed tubers.
- Plant **shallow into warm soil** so sprouts emerge quickly and escape the fungus; avoid cold wet soil.
- Rotate long and leave land fallow where possible; two years fallow substantially reduces severity.
- Harvest promptly once the crop matures rather than leaving tubers in the ground.
- Destroy crop debris and add well-decomposed organic matter."""),

    dict(
        f="potato-tuber-moth", type="Pest", title="Potato tuber moth",
        desc="Caterpillar tunnelling just under the potato skin and pushing frass out at the tuber eyes; multiplies rapidly in unrefrigerated storage.",
        tags="potato, tuber-moth, storage, caterpillar, insect",
        sci="Phthorimaea operculella", crop="potato",
        local="आलू कंद कीट, aloo kand keet, आलू का शलभ", urgency="high",
        sources=src([EAGRI]),
        symptoms="""- On tubers: **irregular winding galleries running just under the skin**, showing as raised dark sinuous lines.
- **Excreta is packed around and pushed out from the tuber eyes**, appearing as brown-black granular piles sitting on the eye buds. This is the key storage symptom.
- Tunnel entrances at the eyes are ringed with dark frass and the flesh beneath darkens and rots.
- On foliage: leaves show **blotchy translucent mines** and the leaf edges are rolled and webbed with silk.
- Growing points die and stems become weak and break over.
- The caterpillar is **pinkish-white to pale greenish with a dark head**, found inside the tuber or the mined leaf.
- Pupae sit in rough silk cocoons coated with soil particles, on the tuber surface, in cracks, or in store corners.
- Adults are small slender moths with **greyish-brown forewings speckled with tiny dark spots**, flying at night.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Cutworm or white grub damage | Tuber moth produces **frass pushed out at the tuber eyes with shallow winding galleries just under the skin**. Cutworms and white grubs gouge open surface craters with clean chewed edges. |""",
        matters="The most destructive potato pest, and it **keeps multiplying inside storage**. A clean field crop can still be destroyed in an unrefrigerated godown.",
        nonchem="""- Plant healthy tubers 10 to 15 cm deep so soil covers them.
- **Earth up thoroughly at about 60 days** so no tuber is exposed for egg-laying.
- Intercrop with chilli, onion or pea.
- Install pheromone traps at about 20 per hectare in the field **and inside the godown**.
- Store only clean tubers in a cool dry ventilated place below 21 degrees Celsius, ideally cold store.
- **Cover the top layer of stored potatoes with lantana or eupatorium branches** to repel egg-laying moths.
- Harvest promptly rather than leaving mature tubers in the soil."""),

    dict(
        f="potato-leafroll-virus", type="Disease", title="Potato leafroll and mosaic viruses",
        desc="Aphid-borne viruses giving stiff leathery upward-rolled leaves that crackle when touched, or mottled crinkled foliage; the main cause of seed potato degeneration.",
        tags="potato, virus, leafroll, mosaic, aphid-borne, seed-degeneration",
        sci="Potato leafroll virus and Potato virus Y", crop="potato",
        local="पत्ती मोड़ विषाणु, patti mod virus, आलू विषाणु रोग", urgency="moderate",
        sources=src([EAGRI,
                     ("potres", "https://link.springer.com/article/10.1007/s11540-022-09540-5",
                      "Species composition and distribution of vector aphids of PVY and PLRV in India")]),
        symptoms="""**Leafroll (PLRV):**

- Leaflets roll **upward from the margins into tight tubes or spoons**, on the lower older leaves in current-season infections and on the top leaves in plants grown from infected seed.
- Rolled leaves become **thick, stiff and leathery, and rattle or crackle audibly when the plant is brushed**. This is the definitive field test.
- Leaves take on a pale yellow cast, and in many varieties the **margins and undersides flush pink to reddish-purple**.
- Plants stand **stiffly upright and stunted**, with a rigid erect posture.
- Cut tubers of some varieties show a fine net of brown dots and streaks in the flesh.

**Mosaic (PVY):**

- Leaves show **light green and dark green mottling and mosaic**, with a marbled uneven surface.
- Leaflets are **crinkled, puckered and rough**, with a raised-and-sunken texture between veins.
- Severe strains produce **black or dark brown dead flecks and streaks along the veins and leaf stalks**, and dead leaves hang down clinging to the stem.

**Both:** small soft-bodied pear-shaped **aphids cluster on leaf undersides and growing tips**, with sticky honeydew and black sooty mould on lower leaves.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Herbicide injury or nutrient stress | Leafroll leaves are **thick, leathery and crackle when handled, on a stiffly upright plant, with aphids on the undersides**. Nutrient and herbicide problems keep leaf texture soft and pliable. |""",
        matters="This is **the primary reason seed potato degenerates** between generations. Yield loss accumulates silently over seasons rather than appearing as a dramatic outbreak.",
        nonchem="""- Plant **certified virus-free seed**. This is the single decisive measure.
- Follow the **seed plot technique**: raise the seed crop in the low-aphid winter window and dehaulm before aphid numbers cross the critical threshold.
- Rogue out symptomatic plants early and repeatedly.
- **Cut the haulm at the right date** to stop late virus movement into tubers.
- Use yellow sticky or water pan traps to monitor aphid flights.
- Keep solanaceous weeds and volunteer potatoes cleared, and isolate seed plots from ware crops."""),

    # ---------------- ONION ----------------
    dict(
        f="onion-thrips", type="Pest", title="Onion thrips",
        desc="Sap-sucking thrips leaving silvery lengthwise streaks speckled with black droppings, hiding deep in the onion leaf axils.",
        tags="onion, garlic, thrips, sucking-pest, insect", sci="Thrips tabaci", crop="onion",
        local="थ्रिप्स, thrips, फुदका, phudka", urgency="high",
        sources=src([EAGRI,
                     ("dogr", "https://www.dogr.res.in/images/AnnualReport/AnnualReport2022.pdf",
                      "ICAR-DOGR Pune Annual Report 2022")]),
        symptoms="""- Leaves develop **silvery-white streaks and blotches running lengthwise**, which glint in sunlight.
- Silvery areas are stippled with **minute dark specks of insect excreta**.
- Leaves curl, wrinkle and twist, and **dry progressively from the tip downward**.
- The insects **congregate deep in the tight leaf axils at the base of the plant and in the neck**, where the leaves wrap. This hiding place is diagnostic — spread the leaves apart to find them.
- Adults are slender yellowish-brown slivers about 1 mm long, just visible to the unaided eye, moving briskly.
- Nymphs are the same shape but paler and wingless.
- **Bulb formation stalls**, so plants stay thin and leek-like with no swelling at the base.
- Whole plots take on a bleached, silvery-grey cast when viewed across the field.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Early purple blotch or nutrient streaking | Thrips damage is **silvery lengthwise streaking speckled with black excreta dots, with live insects packed into the leaf axils at the plant base**. |""",
        matters="Explodes in hot dry weather and stops bulbing entirely. Controlling thrips also directly reduces Stemphylium blight, because thrips wounds and thrips bodies spread that fungus.",
        nonchem="""- Install **sky-blue sticky traps at about 25 per hectare**; blue is markedly more attractive to onion thrips than yellow.
- Avoid growing onion or garlic adjacent to chilli or cotton, which share the pest.
- Use overhead sprinkler irrigation where feasible; free water suppresses thrips.
- Conserve predators such as *Orius*, *Chrysoperla* and predatory thrips.
- Remove and destroy crop residue and volunteer alliums."""),

    dict(
        f="onion-stemphylium-blight", type="Disease", title="Onion Stemphylium blight",
        desc="Fungal leaf blight producing tan lesions with olive-black dusty centres that blight onion leaves from the tip downward.",
        tags="onion, garlic, blight, fungal, stemphylium", sci="Stemphylium vesicarium",
        crop="onion", local="स्टेम्फीलियम झुलसा, patti jhulsa", urgency="high",
        sources=src([("cornell", "https://www.vegetables.cornell.edu/pest-management/disease-factsheets/stemphylium-leaf-blight-of-onion/",
                      "Cornell Vegetables Stemphylium leaf blight of onion"),
                     ("ucipm", "https://ipm.ucanr.edu/agriculture/onion-and-garlic/purple-blotch-and-stemphylium-leaf-blight/",
                      "UC IPM purple blotch and Stemphylium leaf blight")]),
        symptoms="""- Begins as **small yellow to orange flecks in the middle of the leaf blade**, often on the side facing the prevailing wind.
- Flecks stretch into **ovate to elongate, spindle-shaped tan-to-brown lesions**, frequently water-soaked at first.
- Lesions carry **pinkish margins** in early stages with a light yellow water-soaked look.
- As lesions age, **the centre darkens to a uniform olive-brown to sooty black** with a fine dusty velvety surface from heavy spore production.
- Lesions concentrate at and run down from the **leaf tips**.
- Lesions merge and the leaf **dies back and blights from the tip downward**, collapsing and hanging over.
- Whole plots turn a scorched grey-brown at canopy level while bulbs are still sizing.
- Markedly worse where **thrips damage or purple blotch came first**; the fungus colonises pre-injured tissue.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Purple blotch | Stemphylium lesions stay **tan-brown, ovate-elongate with a uniformly dark olive-black dusty sporing centre**. Purple blotch lesions turn magenta-pink to deep purple with an obvious concentric target pattern. |""",
        matters="A re-emerging major foliar disease that shrinks bulbs and compromises storage. It co-occurs with purple blotch constantly, and the two are genuinely hard to separate in a photograph.",
        nonchem="""- **Control thrips first**; this directly reduces Stemphylium colonisation and severity.
- Use certified seed and disease-free transplants.
- **Bury or remove onion leaf residue after harvest**, which delays epidemic start the following season.
- Rotate with non-host crops for at least one year.
- Control weeds in and around the field; nutsedge, pigweed and purslane act as green bridges.
- Wide spacing and base irrigation early in the day to shorten leaf-wetness hours."""),

    # ---------------- BRINJAL ----------------
    dict(
        f="brinjal-little-leaf", type="Disease", title="Brinjal little leaf",
        desc="Phytoplasma disease giving tiny pale leaves pressed flat to the stem, a bushy witches-broom habit and green leaf-like flowers.",
        tags="brinjal, eggplant, phytoplasma, little-leaf, leafhopper-borne",
        sci="Candidatus Phytoplasma trifolii", crop="brinjal",
        local="छोटी पत्ती रोग, chhoti patti rog, बौना रोग, bauna rog", urgency="high",
        sources=src([EAGRI]),
        symptoms="""- Leaves are **dramatically undersized**, a fraction of normal size, while remaining narrow, soft, smooth and pale yellow.
- **Leaf stalks are so short that the tiny leaves appear glued flat against the stem**, giving a stripped, bare-stemmed look.
- Each newly formed leaf is **smaller than the one before it**, so the shoot tapers to a tuft of miniature leaves.
- Stem internodes shorten severely, packing growth into a dense mass.
- **Axillary buds swell and sprout profusely**, producing a thicket of short shoots — a bushy, broom-like witches-broom appearance.
- Flowering mostly stops. Where flowers do form, the **petals stay green and leaf-like** instead of purple.
- Fruit set is very rare, and any fruit formed is hard, small and misshapen.
- Infected plants stand out sharply as small, pale, bushy tufts among normal spreading neighbours.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Herbicide injury or severe leaf curl virus | Little leaf produces **green leaf-like flowers on a bushy witches-broom plant, with leaves stuck flat to the stem on near-absent stalks**. |""",
        matters="A diseased plant gives **100 percent yield loss** and cannot recover. The disease occurs essentially only in India and Sri Lanka, so international references may not cover it.",
        nonchem="""- Uproot and destroy diseased plants **as soon as they are seen**, including plants in neighbouring plots and on bunds, before planting a new crop.
- Keep the field and surrounds clear of weed hosts, particularly *Datura* and periwinkle (*Vinca rosea*), which act as reservoirs.
- Manage the leafhopper vector culturally with yellow sticky traps and by avoiding overlapping brinjal plantings.
- Choose moderately resistant cultivars such as Pusa Purple Cluster, Arka Sheel, Manjari Gota or Banaras Giant.
- Avoid ratooning old brinjal."""),

    dict(
        f="brinjal-phomopsis", type="Disease", title="Brinjal Phomopsis fruit rot and blight",
        desc="Fungal rot turning brinjal fruit into hard black mummies studded with tiny raised black pimples, plus grey-centred leaf spots.",
        tags="brinjal, eggplant, fruit-rot, fungal, phomopsis", sci="Phomopsis vexans",
        crop="brinjal", local="फल सड़न, phal sadan, फोमोप्सिस झुलसा", urgency="high",
        sources=src([EAGRI]),
        symptoms="""- On fruit: **large soft, pale, water-soaked patches** that expand rapidly across the fruit surface.
- Patches darken and the fruit finally becomes **black, hard, shrunken and mummified**, hanging on the plant like a dried lump.
- The **centre of the rotted patch turns grey**, scattered with **numerous tiny raised black pimple-like dots** across the surface.
- In damp weather the black dots ooze fine pale spore tendrils.
- On leaves: clearly defined **circular spots up to about 2.5 cm across, brown to grey in the centre with a narrow dark brown rim**.
- Leaf spots merge and the leaf yellows and drops.
- On seedlings: **dark sunken cankers girdle the stem at or near the soil line**, and the seedling collapses.
- Stems of older plants carry elongated grey-brown sunken cankers dotted with the same black pimples.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Bacterial soft rot | Phomopsis produces **grey-centred lesions studded with tiny raised black pimples, and fruits that dry into hard black mummies**. Bacterial soft rot collapses the fruit into wet slime. |""",
        matters="A major field and post-harvest rot. Mummified fruits left hanging on the plant carry the fungus into the next season.",
        nonchem="""- Use clean seed, with hot-water seed treatment at 50 degrees Celsius for 30 minutes as the documented physical method.
- Pick and destroy all rotted fruits, mummies and blighted leaves from the plant and the ground.
- **Deep summer ploughing** and a **three-year rotation** away from brinjal.
- Destroy crop debris and stubble completely after harvest.
- Wide spacing and staking so fruit hangs clear of the soil.
- Avoid overhead irrigation and working the crop when wet."""),
]

if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bundle", "diseases")
    write_all(CONCEPTS, os.path.normpath(out))
