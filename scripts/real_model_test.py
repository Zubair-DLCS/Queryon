"""End-to-end test with a REAL offline model (downloads it if needed).

    python scripts/real_model_test.py [light|standard|better] [report.md]

Runs chat, all three simplified versions, a quiz and flashcards on a sample
lecture, times each step, and writes everything to a Markdown report so the
quality can be read by a human."""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from queryon.cpu import select_llama_build

select_llama_build()

from queryon.engine import Engine
from queryon.extract import load_document
from queryon.llm import LocalBackend
from queryon.models import BY_ID, download_model, find_model_file

LECTURE = """# Photosynthesis

Photosynthesis is the process by which green plants, algae and some bacteria convert light energy into chemical energy stored in glucose. It is the foundation of almost every food chain on Earth, and it is also the main source of the oxygen in our atmosphere.

## Where it happens

In plants, photosynthesis takes place mainly in the leaves, inside organelles called chloroplasts. A typical leaf cell contains between 20 and 100 chloroplasts. Each chloroplast is surrounded by a double membrane and contains stacks of flattened sacs called thylakoids, which are arranged in piles known as grana. The fluid around the grana is called the stroma.

The green pigment chlorophyll is found in the thylakoid membranes. Chlorophyll absorbs mainly red and blue light and reflects green light, which is why leaves look green. Other pigments, such as carotenoids, absorb additional wavelengths and pass the energy on to chlorophyll.

## The overall equation

The overall reaction can be written as: carbon dioxide plus water, in the presence of light, gives glucose plus oxygen. In symbols: 6CO2 + 6H2O -> C6H12O6 + 6O2. Carbon dioxide enters the leaf through tiny pores called stomata, while water is absorbed by the roots and carried up through the xylem.

## Stage 1: the light-dependent reactions

The light-dependent reactions happen in the thylakoid membranes. Light energy excites electrons in chlorophyll. Water molecules are split in a process called photolysis, releasing oxygen as a by-product, together with hydrogen ions and electrons. The energy from the excited electrons is used to make two energy-carrying molecules: ATP and NADPH.

## Stage 2: the Calvin cycle

The Calvin cycle, also called the light-independent reactions, takes place in the stroma. It does not need light directly, but it depends on the ATP and NADPH produced in stage 1. The enzyme RuBisCO fixes carbon dioxide by attaching it to a five-carbon sugar called RuBP. Through a series of steps, the cycle produces a three-carbon sugar, G3P, which the plant uses to build glucose, starch and cellulose.

## Limiting factors

The rate of photosynthesis is limited by three main factors: light intensity, carbon dioxide concentration and temperature. If any one of these is in short supply, it limits the rate even if the others are plentiful. Temperature matters because the reactions are controlled by enzymes; above about 40 degrees Celsius, the enzymes begin to denature and the rate falls sharply.

Farmers use this knowledge in greenhouses. They can add artificial lighting, burn paraffin to raise both temperature and carbon dioxide levels, and keep the temperature in the best range. This increases crop yield, although the extra cost must be balanced against the value of the extra crop.

## Why it matters

Photosynthesis removes carbon dioxide from the atmosphere and stores carbon in plant material, which makes forests and oceans important carbon sinks. Almost all the energy used by living things, including the energy in fossil fuels, was originally captured by photosynthesis.
"""


def main():
    model_id = sys.argv[1] if len(sys.argv) > 1 else "light"
    report = Path(sys.argv[2] if len(sys.argv) > 2 else "real_model_report.md")
    info = BY_ID[model_id]
    path = find_model_file(info)
    if path is None:
        print(f"Downloading {info.name} ({info.size_gb} GB)...", flush=True)
        last = [0]

        def prog(d, t):
            if d - last[0] > 200 * 1024**2:
                last[0] = d
                print(f"  {d / 1024**3:.2f} / {t / 1024**3:.2f} GB", flush=True)

        path = download_model(info, progress=prog)

    doc_path = Path(tempfile.mkdtemp()) / "Photosynthesis lecture.md"
    doc_path.write_text(LECTURE, encoding="utf-8")
    doc = load_document(doc_path)

    out = [f"# Queryon real-model test\n\nModel: **{info.name}** (`{path.name}`)\n\n"
           f"Document: {doc.words} words in {len(doc.blocks)} parts\n"]
    t0 = time.time()
    backend = LocalBackend(str(path))
    out.append(f"Model load: {time.time() - t0:.1f} s\n")
    eng = Engine(backend, doc)

    def timed(title, fn):
        t = time.time()
        res = fn()
        secs = time.time() - t
        print(f"{title}: {secs:.1f} s", flush=True)
        out.append(f"\n## {title}  \n_{secs:.1f} seconds_\n")
        return res

    for q in ("What is the job of chlorophyll?", "What does RuBisCO do?", "Who discovered photosynthesis?"):
        a = timed(f"Chat: {q}", lambda q=q: eng.chat(q, []))
        out.append(a + "\n")

    for ratio in (0.5, 0.25, 0.1):
        s = timed(f"Simplified {int(ratio * 100)}%", lambda r=ratio: eng.simplify(r))
        out.append(f"{s.words} words ({s.achieved:.0%} of {s.original_words}), mode: {s.mode}\n\n{s.text}\n")

    qs = timed("Quiz (5 questions)", lambda: eng.quiz(5))
    for i, q in enumerate(qs, 1):
        opts = "; ".join(("**" + o + "**") if j == q.answer else o for j, o in enumerate(q.options))
        out.append(f"{i}. {q.question}  \n   {opts}  \n   _{q.explanation}_ ({q.source})\n")

    cards = timed("Flashcards (8)", lambda: eng.flashcards(8))
    for c in cards:
        out.append(f"- **{c.front}**: {c.back} ({c.source})\n")

    out.append(f"\nTotal: {time.time() - t0:.0f} s\n")
    report.write_text("\n".join(out), encoding="utf-8")
    print("Report written to", report)
    ok = len(qs) >= 3 and len(cards) >= 4
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
