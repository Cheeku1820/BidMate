# Reading blueprints better — research note

**Date:** 2026-09-17
**Status:** research, no decision taken. Feeds the sub-projects after B3b.
**Question:** now that Counting finds symbols by shape on exploded vector sheets and *find every one like this* exists, what is the best next step toward reading a drawing set the way an estimator does?

## 1. What the evidence says

### Language models cannot count symbols; they can read legends

Every benchmark that puts a multimodal model in front of a drawing finds the same split. AECV-Bench (120 floor plans, 192 QA pairs) reports OCR and text-centric tasks at up to 0.95 accuracy while "reliable counting of doors and windows remains unsolved (often 0.40–0.55 accuracy) with substantial proportional errors" — the models "function well as document assistants but lack robust drawing literacy". A counting study across model families found Claude systematically under-counts, ChatGPT over-counts and Gemini hallucinates templates, all from "severely degraded spatial localization for non-textual visual elements".

This is exactly the boundary CLAUDE.md already draws: **Counting is geometry, Classification is language.** The research says keep it that way. The model's job is the legend, the schedule, the notes, and naming a crop — never the number.

### The legend is the training set the drawing ships with

Two lines of work turn the legend into the classifier instead of a labelled dataset:

- *Automatic Detection and Classification of Symbols in Engineering Drawings* (2022) locates the legend table, splits it into rows (symbol left, description right), uses each symbol cell as a template, and matches detected symbols to templates with SIFT descriptors: 75 % detection, 75 % classification on 11 test sheets, with the detector named as the bottleneck.
- *Legend-Informed Symbol Recognition in Engineering Diagrams with Self-supervised Learning* (Fraunhofer, ECML-PKDD 2025) trains a symbol encoder by contrasting the legend's own entries with each other — the legend is unique by construction — and matches diagram symbols to legend embeddings at over 80 % accuracy, "generalizing beyond variations in diagram drawing style", with no labelled data.

We have every input these pipelines need and skip the step they centre on. `Sheet.kind == "legend"` is detected, `schedule_text` is extracted, `engine/glyphs.py` can cut the legend sheet's glyph cells the same way it cuts plan glyphs, and `same_shape` already answers "is this the same drawn symbol". What is missing is the join: **legend glyph + adjacent description → a named template → every plan cluster that matches it is named from the legend, deterministically, before any model call.** On the corpus this would name the Kittles receptacles (80/72/43/14), the United Utility receptacle (120) and the Unalaska junction boxes and switches without a key, and leave the model only the clusters the legend does not explain.

### Few-shot detection is the raster answer, and our vector sets can label it for free

On scanned sets there is no geometry to cluster. The state of the practice is a two-stage detector: a one-class "symbol-ness" detector (YOLO / Faster R-CNN) that finds every symbol regardless of type, then a Siamese or contrastive classifier that assigns each detection to a legend template (Gupta, Wei & Czerniawski 2024, *Few-Shot Symbol Detection in Engineering Drawings*: fewer than ten, sometimes one, training instance per class). The 2022 pipeline above trained its detector on 331 cropped symbols.

The asset we hold that the papers lack: **every vector sheet we count is a labelled raster sheet.** Render the page (B3 already does, to 150+ dpi) and the glyph boxes from `glyphs.py` are ground-truth detector labels; the linked tags and legend names are class labels. ArchCAD-400K builds its 400 k-annotation dataset by exactly this trick — harvesting labels from the CAD file's own attributes. Five vector sets today, growing with every pilot upload, produce a detector training set with no annotation work and no NDA exposure beyond the crops themselves.

### Symbol spotting on primitives is where the field is heading

CADSpotting, *Symbol as Points* and FloorPlanCAD treat a CAD drawing as a set of primitives (lines, arcs) and learn panoptic symbol spotting directly on them — the same Tier B geometry `glyphs.py` groups by hand-written rules. These models need labels; ours will accrue from estimator approvals (the per-agent frozen eval set the build stages call for). Not a stage-1 investment, but the rules in `glyphs.py` are the baseline such a model would have to beat, and the approvals are its training data.

### Competitors converge on the same product shape

Countfire (electrical-specific): select a symbol, tell it what it is, it finds every instance across the floor and across every drawing in the project, flags each on the drawing for verification, and re-applies the work to revised drawings. Bluebeam: Visual Search, one sheet at a time. Togal.AI: strong on architectural takeoff, "accuracy gaps on electrical drawings". Kreo/Beam: assistive, no independent accuracy figures. Reviewers put every vendor's 95–99 % claim at 90–95 % on clean plans and lower on scanned or complex sets. Our *find every one like this* matches Countfire's core interaction on one sheet; the two gaps are **set-wide** and **survives a revision**.

### Text on scans

For raster sets the tags (`R`, `F2`) and schedule text need OCR. PP-OCRv5 (PaddleOCR 3.0, May 2025) handles rotated and vertical text with an orientation classifier; users on architectural drawings still report rotated tags flipped or misread, so tag OCR needs the same "tested, not trained" discipline as Counting: assert known tags on known scans.

## 2. What this means for us

In order of value per unit of work:

1. **Legend-named clusters (deterministic).** Cut each legend sheet into (glyph, description) pairs with `glyphs.py` plus adjacent-word association; name every plan cluster whose shape matches a legend glyph from that description; only the remainder goes to the model. Also gives *find every one like this* a name suggestion the moment the box is drawn. No new dependency, no key needed, tested against the corpus legends.
2. **Set-wide match and a project symbol library.** `match` over every plan sheet in the project, and a resolution (named cluster or accepted match) that re-applies to a re-upload or revision of the same set. Closes the two Countfire gaps; the library stays project-scoped until the firm-memory decision is made.
3. **Raster track.** Harvest detector labels from rendered vector sheets; train a one-class symbol detector; classify detections against legend templates by embedding (the Fraunhofer result) with `raster_match` as the fallback; PP-OCRv5 for tags with an asserted-tag test set. This is the only path to honest counts on FedEx/Gerber-style scanned sets.
4. **Verification signals.** Cross-check counts the way an estimator does: fixture-schedule quantities vs counted luminaires, panel-schedule circuit counts vs homerun arrows, receptacle spacing rules. Each disagreement is a *Needs attention* warning with the four fields, not a number the estimator has to notice.
5. **Later:** a primitive-level spotting model trained on approvals, once the eval set exists.

Nothing here moves counting into a language model. The research is unambiguous that this would be a step backwards.

## 3. Sources

- [AECV-Bench: Benchmarking Multimodal Models on Architectural and Engineering Drawings Understanding](https://arxiv.org/abs/2601.04819)
- [Assessing the Visual Enumeration Abilities of Specialized Counting Architectures and Vision-Language Models](https://arxiv.org/html/2512.15254)
- [Automatic Detection and Classification of Symbols in Engineering Drawings](https://ar5iv.labs.arxiv.org/html/2204.13277)
- [Legend-Informed Symbol Recognition in Engineering Diagrams with Self-supervised Learning](https://link.springer.com/chapter/10.1007/978-3-662-72243-5_23)
- [Few-Shot Symbol Detection in Engineering Drawings (Gupta, Wei, Czerniawski 2024)](https://www.tandfonline.com/doi/full/10.1080/08839514.2024.2406712)
- [ArchCAD-400K: An Open Large-Scale Architectural CAD Dataset](https://arxiv.org/html/2503.22346v2)
- [CADSpotting: Robust Panoptic Symbol Spotting on Large-Scale CAD Drawings](https://arxiv.org/pdf/2412.07377)
- [Symbol as Points: Panoptic Symbol Spotting via Point-based Representation](https://arxiv.org/pdf/2401.10556)
- [FloorPlanCAD dataset](https://arxiv.org/pdf/2105.07147)
- [Countfire — Electrical takeoff software](https://www.countfire.com/product/takeoff-software) and [Takeoff key features](https://help.countfire.com/en/articles/4741379-takeoff-key-features)
- [Takeoff tool comparison 2026: Bluebeam vs Togal.AI vs Kreo vs Beam AI](https://www.ruh.ai/blogs/takeoff-tool-comparison-2026)
- [Togal.AI vs Beam AI comparison](https://www.ibeam.ai/blog/togal-vs-beamai-comparison)
- [11 accuracy checks for automated electrical takeoff (drawer.ai)](https://drawer.ai/blog/11-accuracy-checks-for-automated-electrical-takeoff)
- [PaddleOCR rotated text on architectural drawings (discussion)](https://github.com/PaddlePaddle/PaddleOCR/discussions/17325) and [PP-OCRv5 model card](https://huggingface.co/PaddlePaddle/PP-OCRv5_server_det)
