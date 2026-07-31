# -*- coding: utf-8 -*-
"""Fruit and spice concepts: banana, mango, citrus, grape, pomegranate, turmeric, ginger.

Sources: TNAU Agritech, eagri PATH-371/PATH-272/ENTO-331, ICAR-IISR Kozhikode,
ICAR-NRC Pomegranate Solapur, National Horticulture Board.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_concepts import src, write_all

TNAU_F = ("tnau-fruit", "https://agritech.tnau.ac.in/crop_protection/crop_prot_crop_diseases.html",
          "TNAU Agritech Portal crop protection")
EAGRI_F = ("eagri-fruit", "http://eagri.org/eagri50/PATH371/lec02.pdf",
           "TNAU eagri PATH-371 fruit diseases and ENTO-331 horticultural pests")
IISR = ("iisr", "https://www.indianspices.com/sites/default/files/cultivation_practices-ginger.pdf",
        "ICAR-IISR Kozhikode cultivation practices")
NRCP = ("nrcp", "https://nrcpomegranate.in/wp-content/uploads/2025/09/FAQ-English.pdf",
        "ICAR-NRC Pomegranate Solapur")

CONCEPTS = [
    dict(
        f="banana-panama-wilt", type="Disease", title="Banana Panama wilt",
        desc="Soil-borne Fusarium wilt collapsing banana leaves into a dead skirt around the trunk, with the pseudostem base splitting open.",
        tags="banana, wilt, fusarium, soil-borne, tr4", sci="Fusarium oxysporum f.sp. cubense",
        crop="banana", local="पनामा उकठा, panama ukhta, ugra rog", urgency="high",
        sources=src([TNAU_F, EAGRI_F]),
        symptoms="""- Oldest, lowest leaves turn a **bright buttery yellow starting at the leaf margins**, while the middle band along the midrib stays green.
- Yellowed leaves bend sharply downward where the stalk meets the pseudostem and hang down as a **skirt of dead leaves collapsed around the trunk**.
- Leaf margins go dry, papery and pale brown while the rest of the blade is still yellow.
- The **base of the pseudostem splits open in long vertical cracks**, often 20 to 60 cm long, near ground level.
- Cutting the pseudostem across shows **reddish-brown to dark brown dots and rings of discoloured strands** arranged in a circle.
- Cutting the pseudostem lengthwise shows **continuous brown to purple-black lines** running up the stem like pencil streaks.
- Cut corm shows brown to reddish discoloration in a ring near the outer flesh; the tissue is **dry and firm**.
- Younger central leaves stay upright and green for a while, giving a green spear surrounded by yellow collapsed leaves.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Erwinia soft rot | Panama wilt tissue is **dry, firm and streaked brown**. Erwinia rot is wet and slimy with yellowish-red ooze from the cut collar and a strong foul smell. |""",
        matters="Kills the mat over weeks and **the soil stays infested for decades**. Treat an affected block as a long-term land-use decision, not a spray problem.",
        nonchem="""- Dig out and burn the whole affected mat including corm and roots; leave that pit empty.
- Plant only tissue-culture or certified suckers.
- **Wash tools, boots and tyres with soapy water** before moving to a clean block.
- Use flood-free, well-drained beds and avoid moving soil or irrigation water from an affected plot to a clean one.
- Rotate infested land with paddy or sugarcane."""),

    dict(
        f="banana-sigatoka", type="Disease", title="Banana Sigatoka leaf spot",
        desc="Fungal leaf spot producing oval grey-centred spots with yellow halos along banana leaf veins, stripping the canopy.",
        tags="banana, sigatoka, leaf-spot, fungal", sci="Mycosphaerella musicola",
        crop="banana", local="पत्ती धब्बा रोग, patti dhabba rog, sigatoka", urgency="high",
        sources=src([TNAU_F]),
        symptoms="""- Small pale-yellow flecks and thin **streaks running parallel to the leaf veins**, first on the third or fourth leaf from the top.
- Streaks widen into **oval or elliptical spots with the long axis parallel to the veins**, typically 1 to 2 cm long.
- Mature spots have a **light grey to ash-white dry centre** surrounded by a dark brown ring and then a **bright yellow halo**.
- Spots are densest along the **leaf margin and the leaf tip**, often heavier on one half of the blade.
- Many spots run together into **large irregular dried brown patches** and the leaf edge becomes ragged.
- Whole lower leaves dry, turn straw-brown and collapse, leaving few functional green leaves at the top.
- The grey centres feel slightly rough and dusty to the finger.
- Bunches on affected plants are small with fingers that ripen unevenly and early.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Sun scorch or potassium deficiency | Sigatoka shows **discrete oval spots each with a grey centre and yellow halo scattered over the blade**. Scorch shows a continuous even browning band along the margin only. |""",
        matters="Builds over weeks and strips the canopy, shrinking the bunch within one season. Leaves left on the ground keep the spore supply going.",
        nonchem="""- Cut off and remove diseased leaves weekly and bury or burn them away from the field.
- Keep wider spacing and de-sucker to one follower plus one peeper so air moves through.
- Improve drainage and avoid overhead irrigation onto foliage."""),

    dict(
        f="banana-bunchy-top", type="Disease", title="Banana bunchy top virus",
        desc="Aphid-borne virus giving progressively shorter banana leaves in a tight rosette with dark green Morse-code dashes on the midrib.",
        tags="banana, virus, bunchy-top, aphid-borne", sci="Banana bunchy top virus",
        crop="banana", local="गुच्छ शीर्ष रोग, guchh sheersh rog", urgency="high",
        sources=src([TNAU_F]),
        symptoms="""- New leaves emerge **progressively shorter and narrower** than the ones before them, so the plant looks like a funnel.
- Short erect leaves crowd together at the top in a **tight rosette or bunch** with brittle upright blades.
- Leaf margins roll **upward and inward** and become wavy, yellow and dry-edged.
- **Dark green short streaks and dots, like Morse code dashes**, show along the minor veins on the underside of the midrib and on the leaf stalk. Hold the leaf up to sunlight to see them.
- Dark green streaking also appears on the **leaf stalk and the leaf sheaths of the pseudostem**.
- The plant is markedly **stunted**, sometimes half the height of neighbours of the same age.
- Small colonies of **dark reddish-brown to black soft-bodied aphids** cluster deep inside the crown between the youngest leaf sheaths; ants often walk on the pseudostem.
- Where a bunch does form it is tiny with twisted, distorted, hard fingers.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Banana bract mosaic virus | Bunchy top shows **dark green Morse-code dashes along the midrib underside with a stunted rosette**. Bract mosaic shows spindle-shaped pinkish-red streaks on the pseudostem and bracts with a normal-height plant. |""",
        matters="The plant **never bears**. Rogueing must happen before the aphids disperse, so speed of removal decides whether it spreads through the block.",
        nonchem="""- Rogue immediately: dig out the entire mat including corm and all suckers, then burn. Do this before the aphids disperse.
- Take suckers only from blocks symptom-free for a full cycle; prefer tissue culture.
- **Control ants**, which farm the aphids.
- Keep the plantation weeded of wild *Musa* and *Colocasia* hosts."""),

    dict(
        f="mango-hopper", type="Pest", title="Mango hopper",
        desc="Wedge-shaped hoppers swarming mango flower panicles, causing bud shed, sticky honeydew and black sooty mould.",
        tags="mango, hopper, sucking-pest, flowering, insect", sci="Idioscopus niveosparsus",
        crop="mango", local="आम का फुदका, aam ka phudka, भुनगा, bhunga, tudtude", urgency="emergency",
        sources=src([EAGRI_F, TNAU_F]),
        symptoms="""- **Wedge-shaped greenish-brown to grey hoppers, 4 to 5 mm long**, sitting head-down in dense numbers on the flower panicle and tender shoots.
- When the branch is shaken or tapped, insects **jump and fly off sideways in a spray**, making a distinct rustling or crackling sound.
- Panicle stalks, leaves and young fruit are **wet, shiny and sticky with honeydew**, and the sticky film catches dust.
- A **black soot-like coating** spreads over leaves, twigs and panicles, and it **rubs off on the finger as black powder**, leaving green tissue underneath.
- Flower buds shrivel, turn brown and **shed in showers under the tree**, leaving bare panicle stalks.
- Tender shoot tips and young leaves wilt, curl and dry from the tip.
- Between flowering seasons the adults shelter in **cracks and crevices of the trunk bark** and in the dense inner canopy.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Mango mealybug | Hoppers are **fast-moving, wedge-shaped and jump when disturbed**. Mealybugs are slow, oval, coated in white powdery wax, and stay clustered on the stalk. |""",
        matters="**The single biggest flowering-stage threat in mango.** Once panicles are out, a heavy hopper population can take the crop in days.",
        nonchem="""- Open up the canopy by pruning crowded and criss-cross branches so light and air reach inside; dense overcrowded orchards carry the worst attacks.
- Plough or rake the tree basin and remove weeds.
- **Scrape and clean loose bark on the trunk in the off-season** to remove shelters.
- Spray a strong water jet to wash off honeydew and sooty mould.
- Avoid heavy nitrogen, which produces soft flush."""),

    dict(
        f="mango-anthracnose", type="Disease", title="Mango anthracnose",
        desc="Fungal disease blackening mango panicles and producing sunken black fruit spots that run down the fruit in rain tracks.",
        tags="mango, anthracnose, fungal, fruit-rot, post-harvest",
        sci="Colletotrichum gloeosporioides", crop="mango",
        local="आम का एन्थ्रैक्नोज, काला धब्बा, kala dhabba", urgency="emergency",
        sources=src([EAGRI_F, TNAU_F]),
        symptoms="""- **Oval to irregular grey-brown spots on young leaves** that merge into large dead patches; the dry centre becomes brittle and **tears away leaving holes**.
- Leaves on infected stalks hang down limply and drop.
- **Grey-brown elongated spots on green twigs** that enlarge, girdle the shoot and dry it.
- Twigs die **from the tip backwards**, leaving black dead ends on otherwise living branches.
- On flower panicles, **minute black pinhead dots** cover the flower stalks and open flowers in humid weather; the panicle blackens and flowers drop.
- On ripening fruit, **jet-black spots on the skin that sink into shallow craters**, merging into large sunken black patches.
- Black spots are **concentrated at the stem end and run down the sides in vertical streaks and tear-tracks**, following the path rainwater took.
- In humid conditions the sunken black patches carry **salmon-pink to orange slimy spore masses** in the centre.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Stem-end rot | Anthracnose shows **many separate sunken black spots with pink spore ooze spread over the skin**. Stem-end rot shows one solid black patch spreading outward from the fruit stalk, blackening the whole fruit uniformly in two to three days. |""",
        matters="Destroys the flowering crop within days in wet weather, and then **ruins the fruit again after harvest**. It is both a field and a storage problem.",
        nonchem="""- Prune out and burn dead twigs, mummified flowers and hanging dried panicles; these hold the fungus over the dry season.
- Rake up and destroy fallen leaves and fruit.
- Keep the canopy open for airflow.
- Harvest with 3 to 5 cm of stalk attached and handle without bruising.
- **Hot water dip picked fruit at 50 to 55 degrees Celsius for about 15 minutes** before storage."""),

    dict(
        f="mango-powdery-mildew", type="Disease", title="Mango powdery mildew",
        desc="Fungal disease frosting mango flower panicles white and causing heavy fruitlet drop at the critical flowering stage.",
        tags="mango, powdery-mildew, fungal, flowering", sci="Oidium mangiferae",
        crop="mango", local="छाछ्या, chhachhya, सफेद चूर्णी रोग, bhuri", urgency="emergency",
        sources=src([EAGRI_F]),
        symptoms="""- **White to greyish powdery coating like dusted flour or talcum** on the flower panicle stalks, individual flowers and growing tips.
- The powder **wipes off with a finger**, leaving a dull purplish-brown scar on the tissue underneath.
- Whole panicles look **frosted white** from a distance, especially the upper half.
- Powder also coats the underside and upper surface of young leaves, which curl, twist and stay small.
- Affected flowers dry to a **brown, brittle, empty panicle skeleton** and fall.
- Newly set pea- and marble-sized fruitlets carry a **white powdery ring or patch near the stalk end**, then blacken at that point and drop.
- Fruitlets that survive show **corky brown-purple blotches and cracks** where the white coating had been.
- Heavy shedding of tiny fruitlets forms a carpet under the tree.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Mango sooty mould | Powdery mildew is a **white or grey powder growing directly on flowers and young tissue**. Sooty mould is a black film sitting on sticky honeydew. Both rub off, but the colours are opposite. |""",
        matters="Hits at flowering and **can prevent fruit set entirely**. Along with hopper, it decides the crop in the two to three weeks the panicles are out.",
        nonchem="""- Prune and destroy affected panicles as soon as white patches appear.
- Space and prune trees so morning mist dries quickly; avoid a dense inner canopy.
- Remove and burn fallen infected leaves, where the fungus overwinters as dormant mycelium."""),

    dict(
        f="citrus-greening", type="Disease", title="Citrus greening",
        desc="Psyllid-borne bacterial disease giving asymmetric leaf mottle, lopsided fruit with a bent core and dark aborted seeds.",
        tags="citrus, orange, greening, hlb, bacterial, psyllid-borne",
        sci="Candidatus Liberibacter asiaticus", crop="mandarin",
        local="हरितरोग, haritrog, citrus greening, dieback", urgency="high",
        sources=src([EAGRI_F, TNAU_F]),
        symptoms="""- **Blotchy asymmetric yellow mottling on the leaf** — the yellow patches on one side of the midrib sit at different places from those on the other side, so the two halves look mismatched.
- Leaves are **small, upright, thick, leathery and stiff**, with **prominent raised corky veins** standing out like a network.
- Leaf colour is a **dull olive-green with yellow blotches**, sometimes with small green circular islands inside the yellow zones.
- Yellowing appears **on one branch or one sector of the tree first**, giving a lopsided yellow-and-green tree.
- Twigs stand stiffly upright carrying undersized leaves, and shoot tips die back leaving bare sticks.
- **Fruits are small and lopsided**; cutting one lengthwise shows the **central core curved and bent to one side**.
- Fruit colour is **split**: the sunlit side colours orange while the shaded side stays a hard dull olive-green.
- **Seeds inside are dark, shrunken and aborted**; the juice is sparse and sharply sour.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Zinc or manganese deficiency | Greening mottle is **asymmetric across the midrib and comes with lopsided fruit and dark aborted seeds**. Deficiency mottle is symmetrical and identical on both halves of the leaf, and fruit shape stays normal. |""",
        matters="The tree declines over two to five years and **never recovers**. It is the reason citrus orchards across central India have been replanted.",
        nonchem="""- Uproot and burn severely declining trees to remove the bacterial reservoir.
- Plant only certified pathogen-free budded material.
- Manage the psyllid vector and **remove nearby curry leaf (*Murraya*) hedges**, which host it.
- Keep trees vigorous with good manuring and irrigation to slow decline."""),

    dict(
        f="citrus-canker", type="Disease", title="Citrus canker",
        desc="Bacterial disease producing raised corky craters with yellow halos on citrus leaves, twigs and fruit; worst on acid lime.",
        tags="citrus, lime, canker, bacterial", sci="Xanthomonas citri pv. citri",
        crop="mandarin", local="कैंकर, canker, खुरंड रोग, khurand rog", urgency="high",
        sources=src([EAGRI_F, TNAU_F]),
        symptoms="""- **Round raised corky pustules on the leaf, 2 to 5 mm across**, with a crater-like rough centre and a **bright yellow halo ring** around each.
- Pustules **appear on both the upper and lower surface at the same place** and can be felt as a rough bump from either side.
- The **leaf blade around the spots stays flat and normal in shape**, so the pustules stand out on a smooth leaf.
- Older spots turn dry greyish-brown and **crack open** in the centre; a fingernail can flake off the corky crust.
- On twigs and thorns, **elongated raised brown corky lesions** ring the stem and the girdled twig dies back.
- On fruit, **hard raised brown scabby craters with yellow margins** scattered over the rind, while the rest of the rind stays smooth.
- Fruit lesions stay confined to the rind, so the fruit is edible but unsellable.
- Wet weather brings **many new small water-soaked spots on the newest flush**, especially where a leaf miner has made silvery tunnels.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Citrus scab | Canker lesions are **flat-based raised corky craters on a flat undistorted leaf, visible on both surfaces, with a yellow halo**. Scab produces conical wart-like outgrowths that pucker the leaf into a wrinkled shape, with the growth on one surface and a dimple opposite. |""",
        matters="Builds over weeks and disfigures the entire crop within a season. **Wind-driven rain plus thorn injury is the main spread route**, so windbreaks matter more than most orchardists expect.",
        nonchem="""- Prune and burn badly cankered twigs before the monsoon.
- **Set up windbreaks**; wind-driven rain plus thorn injury is the main spread route.
- Remove thorns on young trees.
- Manage citrus leaf miner, whose tunnels are the entry wound.
- Avoid working in the orchard when foliage is wet and disinfect secateurs between trees."""),

    dict(
        f="grape-downy-mildew", type="Disease", title="Grape downy mildew",
        desc="Oomycete disease giving translucent oil-spot patches on grape leaves with white fluffy growth beneath; the fastest-moving grape disease.",
        tags="grape, downy-mildew, oomycete, monsoon", sci="Plasmopara viticola",
        crop="grape", local="मृदुरोमिल आसिता, downy, keva rog", urgency="emergency",
        sources=src([EAGRI_F]),
        symptoms="""- **Pale yellow, translucent oil-spot patches on the upper leaf surface** — hold the leaf to the light and the patch glows through like grease on paper.
- Directly underneath each oil spot, on the **lower leaf surface, a dense white to greyish fluffy downy growth** like fine cotton wool or frost.
- The downy growth is **soft and wipes off** onto the finger.
- Oil spots turn yellow, then brown and papery, and the leaf falls early, leaving bare canes.
- **Tender shoots are dwarfed and twisted**, with sunken brown lesions on the stem.
- Young bunches and berry stalks are **covered in the same white downy growth**, and the whole bunch dries and shrivels.
- Infected young berries turn **grey-brown, leathery and hard, with a smooth unbroken skin**, then shrivel and hang on the bunch.
- Late infection on older berries gives a soft watery rot of the berry flesh.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Grape powdery mildew | Downy mildew growth is **white and fluffy on the LOWER surface beneath a yellow oil spot on the upper surface, and the berry skin stays smooth and intact**. Powdery mildew is a dry grey-white dust on the UPPER surface, and its berries split open. |""",
        matters="**Destroys the crop in days during monsoon.** The fastest-moving disease in grape, and the reason Nashik and Sangli growers watch the forecast daily.",
        nonchem="""- Prune to an open canopy and remove excess leaves in the fruit zone so leaves dry fast after rain.
- Remove and burn fallen infected leaves and mummified bunches at the end of the season; the resting spores overwinter there.
- Improve drainage and avoid overhead or sprinkler irrigation.
- Train vines high off the ground on a proper trellis or pandal."""),

    dict(
        f="pomegranate-bacterial-blight", type="Disease", title="Pomegranate bacterial blight",
        desc="Bacterial disease known as telya giving oily translucent spots that crack pomegranate fruit open in L-shaped splits.",
        tags="pomegranate, telya, bacterial, blight, oily-spot",
        sci="Xanthomonas axonopodis pv. punicae", crop="pomegranate",
        local="तेल्या रोग, telya rog, जीवाणु झुलसा", urgency="emergency",
        sources=src([NRCP, TNAU_F]),
        symptoms="""- **Small water-soaked, translucent oily spots on the underside of the leaf** — hold the leaf to the light and they glow through like drops of oil on paper.
- Spots enlarge and the centre goes dark brown to black, often with a narrow water-soaked border still visible around the dead centre.
- On fruit, **water-soaked oily spots on the outer rind** that darken into **black-brown irregular greasy blotches**.
- Fruit blotches enlarge and the rind **cracks open in an L-shaped or Y-shaped split**, exposing the arils; the whole fruit then darkens and dries.
- **The spots feel sticky and slippery to the finger** when a drop of water is placed on them and rubbed. This is the field ooze test.
- On twigs, **grey water-soaked tissue forms a band around the nodes**, mostly on new young shoots.
- Node bands turn **brown-black with water-soaked margins**, and the twig **snaps easily at the blackened node**.
- In young orchards from latently infected planting material, blackening of nodes just above ground level appears about five to seven months after planting.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Cercospora or Alternaria fruit spot | Bacterial blight spots are **greasy, translucent against light and sticky to the touch, with blackened banded nodes on the twigs**. Cercospora and Alternaria spots are dry and matt, confined to fruit and leaf, with clean twigs. |""",
        matters="Sixty to one hundred percent fruit yield loss in a bad year. **Hardwood cuttings and air layers carry latent infection in the nodes**, so the disease travels with planting material into new districts.",
        nonchem="""- Plant only **tissue-culture material** in new or non-traditional areas; cuttings and air layers carry latent infection.
- Prune out and burn all infected twigs and leaves and collect fallen infected material, during the dry period.
- Avoid working in the orchard when foliage is wet; disinfect secateurs between plants.
- Take a rest period with no bahar in badly hit orchards.
- Bag fruits and provide windbreaks; wind-driven rain spreads it."""),

    dict(
        f="turmeric-rhizome-rot", type="Disease", title="Turmeric rhizome rot",
        desc="Oomycete soft rot turning turmeric rhizomes into a foul-smelling brown mush and collapsing the whole clump.",
        tags="turmeric, ginger, rhizome-rot, oomycete, soil-borne",
        sci="Pythium aphanidermatum", crop="turmeric",
        local="प्रकंद गलन, prakand galan, गांठ सड़न", urgency="emergency",
        sources=src([IISR, TNAU_F]),
        symptoms="""- **Leaves dry inward starting from the margins and the tip**, so the green area shrinks to a narrowing central strip.
- The **collar region where the pseudostem meets the soil turns soft, water-soaked and translucent**, and the stem can be pulled out with a light tug.
- The pulled pseudostem **separates cleanly at the collar**, leaving the rhizome behind in the ground.
- Affected pseudostems bend over and the **whole clump collapses flat** on the bed.
- Digging shows the **rhizome soft, pulpy, watery and light to dark brown**, turning to wet mush under thumb pressure.
- Cut rhizome shows the **bright orange-yellow flesh replaced by a dull brown-grey soggy mass**.
- The rotten rhizome and surrounding soil carry a **strong sour, foul smell**.
- Damage occurs in **patches following the water flow line**, spreading downslope in the bed.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Dry rot (*Rhizoctonia bataticola*) | Rhizome rot leaves the tissue **wet, soft, pulpy and foul-smelling with a water-soaked collar**. Dry rot leaves the rhizome dry, hard, shrunken and corky. |""",
        matters="Kills the clump within days to weeks once monsoon rain sets in. **Water stagnation is the trigger**, so bed preparation decides the outcome more than anything applied later.",
        nonchem="""- Plant on **raised ridges or beds with strong drainage channels**; avoid water stagnation absolutely.
- Select seed rhizomes only from disease-free plots.
- **Solarize beds under transparent polythene for 40 to 50 days** before planting.
- Deep-plough in summer and follow crop rotation; avoid continuous turmeric.
- Remove affected clumps with the surrounding soil and destroy them away from the field.
- Apply well-decomposed farmyard manure and composted neem cake at planting."""),

    dict(
        f="ginger-soft-rot", type="Disease", title="Ginger soft rot",
        desc="Seed and soil-borne oomycete rot yellowing ginger from the leaf tips down and turning rhizomes into foul-smelling pulp.",
        tags="ginger, soft-rot, rhizome-rot, oomycete, seed-borne",
        sci="Pythium aphanidermatum", crop="ginger",
        local="नरम गलन, naram galan, कंद सड़न", urgency="emergency",
        sources=src([IISR, TNAU_F]),
        symptoms="""- **Light yellowing that begins at the TIPS of the lower leaves** and then creeps down the blade.
- Early on the leaf shows a striking pattern: **the middle strip along the midrib stays green while both margins turn yellow**.
- Yellowing then climbs from the lowest leaves upward until the whole plant is yellow.
- Yellowed leaves droop, wither and dry, and the pseudostems flop over.
- The **collar region is water-soaked, dark and soft**, and the shoot **pulls out of the soil with a light tug**.
- Dug rhizome is **soft, pulpy, watery and pale to dark brown**, collapsing under finger pressure.
- The rot gives off a **characteristic strong foul smell**.
- Later the roots also rot and the clump lifts out with almost no root system.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Ginger bacterial wilt | Soft rot yellowing **starts at the leaf tips and margins with the mid-strip staying green**, and the cut rhizome is soft wet rot with a foul smell. Bacterial wilt begins with drooping and inward curling of the leaf **margins**, and pressing the cut pseudostem squeezes out **milky-white ooze**. |""",
        matters="**The single most destructive ginger disease.** Total loss of affected clumps in days to weeks. It is seed-borne, so it travels with the planting material.",
        nonchem="""- Take seed rhizomes **only from disease-free gardens**; the disease is seed-borne.
- Plant on well-drained beds; water stagnation is the trigger.
- **Solarize beds under transparent polythene for 40 to 50 days.**
- Apply *Trichoderma harzianum* with composted neem cake to the bed at planting.
- Once seen, remove affected clumps carefully with the surrounding soil and destroy them away from the field."""),

    dict(
        f="ginger-bacterial-wilt", type="Disease", title="Ginger bacterial wilt",
        desc="Soil and seed-borne bacterial wilt of ginger confirmed by milky white ooze squeezed from the cut pseudostem.",
        tags="ginger, bacterial, wilt, ralstonia, soil-borne",
        sci="Ralstonia solanacearum", crop="ginger",
        local="जीवाणु उकठा, jeevanu ukhta, जीवाणु मुरझान", urgency="emergency",
        sources=src([IISR, TNAU_F]),
        symptoms="""- **Water-soaked dark spots at the collar region** of the pseudostem that spread both upward and downward.
- The first noticeable sign is a **mild drooping with the leaf margins curling inward** on the lowest leaves, like a leaf rolling in on itself.
- Curling and drooping spread **from the lower leaves upward**, and severe yellowing follows.
- The plant **wilts while the leaves are still green or only partly yellow**, and stays standing but limp.
- Cutting the pseudostem across shows **dark brown to black streaks in the vascular ring**.
- **Gently pressing the cut pseudostem or rhizome squeezes out a milky-white sticky ooze** from the cut strands. This is the definitive field test. Suspending the cut stem in clear water gives white threads streaming down.
- The rhizome finally rots and gives off a foul smell.
- Wilting appears in **patches that widen along the direction of irrigation water flow**.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Ginger soft rot | Bacterial wilt gives **milky-white ooze from the cut vascular strands and dark vascular streaks**, wilting while leaves are still green. Soft rot gives a wet pulpy foul rot with tip-first yellowing and no milky ooze. |""",
        matters="Destroys the clump in days and **spreads down the irrigation line**, so field layout and water direction decide how far it goes.",
        nonchem="""- Take seed rhizomes only from disease-free fields.
- **Avoid fields that previously grew potato, tomato, chilli, brinjal or peanut**; all host the same bacterium.
- Avoid planting ginger in the same field in consecutive years.
- Remove affected clumps carefully without spilling the surrounding soil, and burn them far from the field.
- Provide drainage and prevent runoff from an affected patch to a clean one; solarize beds."""),
]

if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bundle", "diseases")
    write_all(CONCEPTS, os.path.normpath(out))
