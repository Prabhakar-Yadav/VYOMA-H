# Research Summary: Rural Literacy AI Tutors & Open Data Sources

**Project:** Gram Sahayak (AI Tutor Module for VYOMA Innovation Challenge)  
**Author:** Palak Verma (IIT Kanpur | VaultStack AI)  
**Objective:** Benchmarking existing rural education platforms in India and identifying optimal open datasets for foundational literacy (Class 5th–8th).

---

## 1. Existing Products & Frameworks in India (Benchmarking)

| Platform / Product | Creator / NGO | Delivery Channel | Features & Limitations | How Gram Sahayak Beats It |
| :--- | :--- | :--- | :--- | :--- |
| **Read Along (Bolo)** | Google | Android App (Mobile) | Speech-based reading tutor for primary kids. Requires smartphone. | **Suno Sutra Edge Device:** Dedicated handheld hardware, zero smartphone requirement, 100% offline. |
| **Sampark Smart Shala (Tara)** | Sampark Foundation | Smart TV / Audio Box | Offline audio lessons for primary school teachers in rural classrooms. | **Interactive Voice + LCD:** Individualized Q&A via local OKF RAG engine rather than fixed audio playback. |
| **SwiftChat (ConveGenius)** | ConveGenius | WhatsApp Bot | Conversational learning bot used by state school boards in India. | **Zero Connectivity:** Operates in 4G dead-zones where WhatsApp bots fail. |

---

## 2. Top Open Datasets for Rural Literacy & School Curriculum

1. **ShikshaEdge NCERT Dataset (Kaggle):**  
   * Pre-cleaned Q&A pairs for Indian rural classrooms across Hindi, Marathi, and regional languages. (Ingested into `ai_tutor_rag.py`).
2. **DIKSHA National Repository (NCERT / Govt of India):**  
   * Official e-learning textbooks and lesson JSON files spanning Class 1st–8th across 30+ regional languages.
3. **Pratham Books & StoryWeaver Platform:**  
   * Open-license (CC-BY 4.0) leveled children's storybooks in 300+ Indian languages and tribal dialects (ideal for basic reading literacy).

---

## 3. Our Unique Advantage: Voice + 2.8" TFT LCD Display

* **The Visual Literacy Gap:** Audio-only learning fails for foundational reading. Students need to see letters, words, and numbers.
* **Gram Sahayak's Solution:** Our Google OKF RAG engine outputs **dual multimodal responses**:
  1. **Visual Card (2.8" TFT LCD):** Displays formatted text cards (*e.g., "A for Apple", "50 + 50 = 100"*).
  2. **Regional Dialect Audio (Bhashini TTS):** Speaks the lesson out loud through the 5W speaker in local village dialects (*Bhojpuri, Varhadi, Awadhi*).
