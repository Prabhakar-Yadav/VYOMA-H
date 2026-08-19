# Goa State Government Schemes Master Database (2026 Edition)
> **Comprehensive State-Level Agricultural & Environmental Policy Framework**  
> **State Code:** `GA` / `GOA`  
> **Key State Focus Areas:** Fallow & Abandoned Land Reclamation (*Padat Land Cultivation Assistance* - ₹30,000 + ₹10,000/ha), Solar Grid-Tied Agro-Cold Chains (60% Subsidy up to ₹8 Lakh for Mango/Cashew/Jackfruit), Coastal Khazan Land Farming, *Krishi Card* Digital Verification  
> **State Portals:** `agri.goa.gov.in`, `goa.gov.in`

---

## Executive Summary & State Operational Context

Goa's state agricultural policy focuses on the unique agronomic conditions of the Konkan coastal strip, estuarine lowlands (*Khazan lands*), and inland red-loam hill tracts (*Morod lands*):
1. **Fallow Land Revitalization (Padat Land Cultivation):** Addressing abandoned agricultural plots with a ₹30,000/ha clearing and plowing input grant, followed by a ₹10,000/ha bonus for sustained cultivation over two consecutive seasons.
2. **Post-Harvest Cold Chains & Green Energy:** 60% capital grants (up to ₹8 Lakh) for solar-powered on-farm pre-cooling rooms and walk-in cold chambers for perishable coastal produce (Alphonso/Mankurad mangoes, Jackfruit, Cashew apples).
3. **Institutional Farmer Identity (Krishi Card & Form I & XIV):** Comprehensive e-governance linking land ownership (Form I & XIV) and *Comunidade* leases directly to the Goa Krishi Card for streamlined DBT payouts.

---

## Section 1: Sustainable Land Management & Fallow Reclamation

### [GOA_SCHEME_005] Scheme for Promotion of Cultivation on Fallow Land (Padat Land Assistance)
* **Category:** Sustainable Land Management & Production Expansion
* **Target Beneficiary:** Individual landholders, Self-Help Groups (SHGs), tenant groups, and *Comunidades* bringing long-term uncultivated or fallow land (*Padat Land*) back under active cultivation.
* **Benefit Details:** Financial assistance to revive abandoned rural agricultural land:
  * Direct financial input incentive grant of ₹30,000 per Hectare for initial de-weeding, clearing of wild thickets, and deep tractor plowing of fallow plots.
  * An additional cash bonus transfer of ₹10,000 per Hectare delivered via DBT if the reclaimed land is successfully cultivated with local varieties of paddy, pulses (cowpea / *Alsande*), or sweet potatoes for two consecutive seasons.
* **Eligibility Criteria:** Agricultural land parcel must be officially certified as uncultivated or fallow for a minimum continuous duration of 3 preceding years by the local Zonal Agricultural Officer (ZAO).
* **How to Apply:** Handled offline by submitting application files through the village Panchayat or local ZAO. Agricultural officers conduct a mandatory pre-clearing site inspection to verify the baseline fallow status.
* **Documents Required:** Aadhaar Card, valid Goa Krishi Card, digital copy of Form I & XIV, fallow-status verification slip signed by the local ZAO, and bank passbook.

---

## Section 2: Post-Harvest Solar Cold Storage Infrastructure

### [GOA_SCHEME_006] Chief Minister's Solar Power Grid-Tied Agro-Cold Chain Subsidy
* **Category:** Post-Harvest Cold Storage & Green Energy Infrastructure
* **Target Beneficiary:** Progressive farmers, horticultural cooperatives, and rural food-processing entrepreneurs handling perishable crops (Mankurad/Alphonso Mango, Jackfruit, Cashew apple processing).
* **Benefit Details:** Capital grants for establishing localized, eco-friendly cold chains:
  * 60% capital investment subsidy (up to a financial ceiling of ₹8 Lakh per project) to install on-farm solar-powered pre-cooling rooms, walk-in cold chambers, and multi-commodity temperature-controlled storage units (3 MT to 10 MT capacities).
  * Rooftop solar photovoltaic arrays generate green energy for refrigeration, with all surplus power exported back to the state electricity grid under a guaranteed net-metering buyback framework.
* **Eligibility Criteria:** Registered farmers or farmer cooperatives with dedicated unshaded on-field roof or yard space clear of high-voltage transmission line interference.
* **How to Apply:** Digital proposals and technical layouts are submitted through the Directorate of Agriculture portal or directly to the regional ZAO.
* **Documents Required:** Aadhaar Card, Krishi Card, complete Form I & XIV land record, itemized machinery proforma quotes from an empanelled vendor, and No-Objection Certificate (NOC) from the Electricity Department.

---

## Section 3: Ground Application Workflows & Konkani Lexicon

| Regional Term | Operational Context & Significance |
| :--- | :--- |
| **Padat Land** | Long-term fallow or uncultivated rural land certified by the ZAO as abandoned for at least 3 years. |
| **Krishi Card** | Smart digital identity card issued by the Directorate of Agriculture, Goa, linking farmer profiles to state subsidies. |
| **Form I & XIV** | Official land revenue record proving land ownership, survey number, and tenant cultivation status in Goa. |
| **ZAO (Zonal Agricultural Office)** | Block-level agricultural administration responsible for field inspections, Krishi Cards, and subsidy verification. |
| **Comunidades** | Ancient village community collective land-owning institutions governing agricultural and Khazan land leases in Goa. |
| **Khazan Lands** | Low-lying coastal estuarine agricultural wetlands protected by saline dykes and sluice gates (*Manos*). |

---

## Section 4: Master JSON Lines for Engine Indexing

```json
{"scheme_id": "GOA_SCHEME_005", "scheme_name": "Padat Land Cultivation Assistance", "category": "Sustainable Land Management", "target_beneficiary": "Individual landholders, SHGs, and Comunidades bringing fallow land under cultivation", "benefit_details": "Rs 30,000/ha for clearing/plowing uncultivated land plus Rs 10,000/ha bonus for 2 consecutive seasons of cultivation.", "eligibility_criteria": "Land officially certified as fallow for 3+ years by ZAO via Form I & XIV and Krishi Card.", "how_to_apply": "Apply via local Zonal Agricultural Office (ZAO) or village Panchayat.", "documents_required": "Aadhaar Card, Goa Krishi Card, Form I & XIV, ZAO fallow verification slip, bank passbook.", "contact_details": "Directorate of Agriculture, Goa. Portal: agri.goa.gov.in", "last_verified": "2026-08", "searchable_text": "goa goa_scheme_005 padat land fallow land cultivation assistance uncultivated land 3 years paddy pulses 30000 10000 per hectare zao form i xiv krishi card"}
{"scheme_id": "GOA_SCHEME_006", "scheme_name": "Chief Ministers Solar Power Grid Tied Agro Cold Chain Subsidy", "category": "Post-Harvest Infrastructure", "target_beneficiary": "Farmers, cooperatives, and fruit processors handling mango, cashew, and jackfruit", "benefit_details": "60% capital subsidy (Rs 8 Lakh cap) for on-farm solar-powered pre-cooling rooms and walk-in cold storage with net metering.", "eligibility_criteria": "Registered farmers/groups with unshaded roof/yard space and Electricity Department NOC.", "how_to_apply": "Submit project proposal to Directorate of Agriculture or regional ZAO.", "documents_required": "Aadhaar Card, Krishi Card, Form I & XIV, vendor proforma invoice, Electricity Department NOC.", "contact_details": "Directorate of Agriculture & Department of Power, Goa. Portal: agri.goa.gov.in", "last_verified": "2026-08", "searchable_text": "goa goa_scheme_006 solar cold chain pre cooling walk in cold room net metering electricity department mango jackfruit cashew 60 subsidy 8 lakh ceiling zao"}
```
