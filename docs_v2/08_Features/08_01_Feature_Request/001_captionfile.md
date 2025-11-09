**Feature Request: Add Stable Diffusion Caption Output & File Generation Without Changing Existing Behavior**

**Summary**
Extend the current image-analysis workflow so that, in addition to producing the existing JSON for social media purposes, the system also generates a Stable-Diffusion-ready caption file. Existing behavior — including description, mood, tags, nsfw, and safety_labels — must remain unchanged and fully intact.

**Objective**
Alongside the current JSON output, extract an additional structured caption string optimized for fine-art photography training and save it as a `.txt` file next to the image. The caption must include pose description, styling/material cues, lighting, and artistic photography terms. This file will be used for model-training labels and must not interfere with the current social media captioning pipeline.

**Requirements**

1. **Do not modify or break the existing JSON structure or fields.**
2. Add a new field to the model output:
   `sd_caption` — a single-sentence training caption for Stable Diffusion.
3. The `sd_caption` must include:

   * fine-art photography style wording
   * pose description
   * styling materials (e.g., rope body-form styling, fabric wrap, minimalist wardrobe)
   * lighting & mood terms
4. After the response is received, create a `.txt` file:

   * same directory as image
   * same filename base (`image.jpg` → `image.txt`)
   * content = only the `sd_caption` text (one line)
   * overwrite if exists
5. Caption structure must remain PG-13 and artistic (no explicit terms).

**Caption File Example**

```
low-key studio figure study,single person, female,brown hair, slender figure, rope body-form art styling, standing pose with relaxed arms, dramatic side lighting, fine-art portrait photograph
```

**Acceptance Criteria**

* Existing social-media JSON output remains identical and untouched
* A new `sd_caption` field is added to the JSON response
* A `.txt` file is created for each image containing only the SD caption
* Caption includes pose + styling + lighting + fine-art descriptors
* Re-processing an image safely overwrites the caption file
* When the image is moved to the archive, so is the caption file
