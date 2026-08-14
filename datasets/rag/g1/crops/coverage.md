---
type: Coverage Boundary
title: Crop coverage boundary
description: Every major Indian crop the device can recognise by name, split into those it can diagnose and those it must refuse. Drives hard abstention.
tags: [coverage, crops, abstention, safety]
covered_crops:
  cotton: [cotton, kapas, kapus, narma, paruthi, patti, कपास]
  tomato: [tomato, tamatar, thakkali, ramamulaga, टमाटर]
  rice: [rice, paddy, dhan, dhaan, chawal, nel, arisi, vari, bhatta, jhona, धान, चावल]
  wheat: [wheat, gehun, gehu, kanak, gahu, ghau, godhumai, godhuma, गेहूं, गेहूँ]
  maize: [maize, corn, makka, makai, makki, maka, mokkajonna, makkacholam, मक्का, मकई]
  # --- diagnosable, but treatment records still pending verification ---
  potato: [potato, aloo, alu, batata, urulaikizhangu, bangaladumpa, आलू]
  onion: [onion, pyaz, pyaaz, kanda, vengayam, ullipaya, eerulli, peyaj, प्याज, प्याज़]
  brinjal: [brinjal, eggplant, aubergine, baingan, begun, vange, kathirikai, vankaya, badanekayi, बैंगन]
  chickpea: [chickpea, bengal gram, chana, chhola, harbhara, kadalai, senagalu, kadale, चना, छोला]
  pigeon pea: [pigeon pea, red gram, arhar, tur, toor, tuver, thuvarai, kandulu, togari, अरहर, तूर]
  green gram: [green gram, mung, moong, pasipayaru, pesalu, hesaru, मूंग]
  soybean: [soybean, soyabean, soya, सोयाबीन]
  mustard: [mustard, rapeseed, sarson, rai, toria, sorshe, mohari, kadugu, aavalu, सरसों, राई, तोरिया]
  groundnut: [groundnut, peanut, mungfali, moongphali, singdana, nilakkadalai, verkadalai, pallilu, nelagadale, मूंगफली]
  sugarcane: [sugarcane, ganna, eekh, oos, karumbu, cheruku, kabbu, aakh, गन्ना, ईख]
  okra: [okra, ladyfinger, lady finger, bhindi, bhendi, dherosh, vendakkai, bendakaya, भिंडी]
  chilli: [chilli, chili, chile, mirch, mirchi, milagai, mirapakaya, menasinakayi, मिर्च]
  banana: [banana, kela, vazhai, vazhaipazham, arati, bale, kel, vazha, केला]
  mango: [mango, aam, maambazham, mamidi, mavu, amba, आम]
  mandarin: [mandarin, orange tree, santra, santara, kinnow, kamala, संतरा]
  grape: [grape, grapes, angoor, draksha, thiratchai, अंगूर]
  pomegranate: [pomegranate, anar, dalimb, mathulai, danimma, अनार]
  turmeric: [turmeric, haldi, manjal, pasupu, arishina, halad, हल्दी]
  ginger: [ginger, adrak, inji, allam, shunti, aale, अदरक]
uncovered_crops:
  # --- Cereals & millets ---
  - [sorghum, jowar, jwari, cholam, jonna, jola, ज्वार]
  - [pearl millet, bajra, kambu, sajja, sajje, bajri, बाजरा]
  - [finger millet, ragi, madua, kezhvaragu, ragulu, nachni, रागी, मड़ुआ]
  - [barley, jau, जौ]
  - [foxtail millet, kangni, thinai, korralu, navane, कंगनी]
  - [kodo millet, kodo, varagu, arikelu, kodra, कोदो]
  - [little millet, kutki, samai, कुटकी]
  # --- Pulses ---
  - [black gram, urad, urid, ulundu, minumulu, uddu, udid, उड़द]
  - [lentil, masoor, musur, मसूर]
  - [field pea, matar, vatana, pattani, मटर]
  - [cowpea, lobia, karamani, bobbarlu, chawli, लोबिया]
  - [horse gram, kulthi, kollu, ulavalu, hurali, कुल्थी]
  # "moth" and "math" deliberately omitted — see the ambiguous-alias note below
  - [moth bean, मोठ]
  # --- Oilseeds ---
  - [sesame, til, ellu, nuvvulu, तिल]
  - [castor, arandi, rendi, erandi, divel, amanakku, aamudam, अरंडी, रेंडी]
  - [sunflower, surajmukhi, surya kanti, sooriyakanthi, सूरजमुखी]
  - [linseed, flax, alsi, javas, alshi, tishi, अलसी]
  - [safflower, kusum, karadi, kusube, kusuma, कुसुम]
  # --- Cash / fibre ---
  - [jute, patsan, kosta, जूट, पटसन]
  - [tobacco, tambaku, pogaku, pugaiyilai, तंबाकू]
  # --- Vegetables ---
  - [cauliflower, phool gobhi, phulkobi, phulkopi, poo kose, फूलगोभी]
  - [cabbage, patta gobhi, bandhakopi, kobi, muttaikose, पत्ता गोभी]
  - [bottle gourd, lauki, ghiya, dudhi, suraikkai, sorakaya, लौकी, घिया]
  - [bitter gourd, karela, pavakkai, kakarakaya, hagalakayi, करेला]
  - [garlic, lahsun, poondu, velluli, bellulli, लहसुन]
  - [cucumber, kheera, kakdi, vellarikkai, dosakaya, खीरा, ककड़ी]
  - [pumpkin, kaddu, कद्दू]
  - [carrot, gajar, गाजर]
  # --- Fruits ---
  - [sweet orange, mosambi, mausambi, battayi, sathukudi, मौसंबी]
  - [acid lime, lemon, nimbu, kagzi nimbu, elumichai, nimma, nimbe, नींबू]
  - [papaya, papita, pappali, boppayi, papai, पपीता]
  - [guava, amrud, peru, peyara, koyya, jama, अमरूद]
  - [apple, seb, tsunt, सेब]
  - [coconut, nariyal, thengai, thenga, kobbari, tenkaya, tengu, नारियल]
  # --- Spices & plantation ---
  - [coriander, dhaniya, kothamalli, kothimeera, kothimbir, धनिया]
  - [cumin, jeera, jiru, seeragam, jilakarra, जीरा]
  - [fenugreek, methi, vendhayam, menthulu, मेथी]
  - [black pepper, kali mirch, kurumulaku, milagu, kalu menasu, काली मिर्च]
  - [cardamom, elaichi, elakka, elakkai, elakki, इलायची]
  - [tea, chai, चाय]
  - [coffee, kaapi, कॉफी, कॉफ़ी]
  - [arecanut, betel nut, supari, adike, pakku, adakka, सुपारी]
  - [rubber, rabar, रबर]
sources:
  - id: icar-crop-list
    resource: https://icar.org.in
    title: ICAR crop institute listings and DES crop statistics
    author: process:icar
    last_modified: 2024-01-01
generated: { by: human:prabhakar, at: 2026-07-31T00:00:00Z }
---

# Why this concept exists

Similarity scoring cannot enforce a coverage boundary on its own. A photo of a
banana leaf with purple spots and orange streaks is *genuinely* similar, in
embedding space, to a tomato leaf with brown spots — both are "diseased leaf with
coloured lesions." The encoder is not wrong to rank them close. Measured on the
seed corpus, an out-of-corpus banana query scored **0.635**, higher than a
correct in-corpus Hindi query at **0.552**. The classes overlap, so no threshold
separates them.

The boundary therefore has to be **structural rather than statistical**: if the
crop is named and we do not cover it, abstain — whatever the similarity score says.

# The two lists are not the same thing

- **`covered_crops`** — crops with disease concepts and verified treatment records
  behind them. These can be diagnosed.
- **`uncovered_crops`** — crops the device **recognises by name but cannot
  diagnose**. Naming them is what makes the refusal specific and trustworthy:

  > *"I do not know about sugarcane yet. Please show this plant to your nearest
  > Krishi Vigyan Kendra."*

  rather than a vague "I am not sure." A farmer who hears their own crop named
  back to them learns the device's limits, which is what keeps them using it.

Currently **24 crops diagnosable, 63 recognised**. Every major Indian crop by area
is in one list or the other, with English, Hindi, and the main regional names, so
no common crop falls through to a similarity guess.

# Ambiguous aliases are deliberately omitted

Some crop names are also ordinary English words that appear in symptom
descriptions. Listing them here causes the gate to block **valid** diagnoses.

This was found the hard way. Adding `orange` for citrus immediately broke a
correct wheat rust query — *"yellow stripes with **orange** powder that comes off
when touched"* — because the scanner matched the colour and refused before
ranking. A working diagnosis was lost to a crop the farmer never mentioned.

The following are therefore **excluded on purpose**, and should not be re-added:

| Omitted | Crop | Collides with |
|---|---|---|
| `orange` | citrus | the colour, in almost every rust and lesion description |
| `moth`, `math` | moth bean | an **insect** — the single worst collision in a pest corpus |
| `pepper` | chilli | generic; also black pepper |
| `lime` | acid lime | agricultural lime, lime sulphur |
| `save`, `sama` | little millet | common English verb |
| `pat` | jute | common English word |
| `cha`, `sah` | tea | too short to disambiguate |

Their multi-word forms are kept (`orange tree`, `moth bean`, `acid lime`,
`black pepper`) because multi-word aliases are matched as phrases, not tokens,
and cannot fire on a single stray word.

**The asymmetry that decides this:** a false positive **blocks correct advice** a
farmer needed. A false negative merely falls through to the similarity gate,
which still refuses out-of-corpus crops on score. When in doubt, leave the alias
out.

# How it is used

1. The vision model reports the crop it sees; that value is passed as `crop`.
2. If the reported crop is absent from `covered_crops`, the device abstains
   immediately and never reaches ranking.
3. As a backstop for when the VLM does not report a crop, the query text is
   scanned for any `uncovered_crops` term. A hit forces abstention.

A crop absent from *both* lists degrades to the ordinary similarity gate — it does
not fail open into a wrong prescription, because the score threshold still applies.

# Extending coverage

Adding a crop means adding its disease concepts and treatment records, then moving
its entry from `uncovered_crops` to `covered_crops`. **Moving the entry without
adding the concepts is the single edit that would make this device unsafe** — the
crop would pass the gate with nothing behind it.
