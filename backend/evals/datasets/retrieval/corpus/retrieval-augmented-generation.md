# Grounding generation in retrieved documents

A language model asked a factual question answers from weights alone, and has no way to
signal which parts of the answer it is confident in. Retrieval-augmented generation
changes the input rather than the model: relevant passages are fetched from a document
store first and supplied alongside the question, so the answer is conditioned on text the
system can point back to.

The benefit is not only accuracy. Because the passages are supplied rather than recalled,
each statement can be tied to a source that a reader can open, and updating what the
system knows means updating the store rather than retraining anything.

The failure mode moves accordingly: if retrieval returns the wrong passages, a fluent and
well-cited answer can still be wrong. Retrieval quality becomes the ceiling on output
quality.

Chunk size is the first real decision. Passages short enough to be precise are often too
short to carry the context that makes them interpretable, and passages long enough to be
self-contained dilute the signal that made them retrievable. Overlapping windows are the
usual compromise, at the cost of returning the same sentence more than once.

Evaluation is harder than it looks, because two failures wear the same face. An answer can
be wrong because retrieval never surfaced the passage that contained the fact, or because
the passage was surfaced and the model ignored it. Measuring only the final answer cannot
separate them, which is why retrieval is scored on its own before generation is scored at
all.

Freshness is the quiet advantage. Updating a store is a write; updating weights is a
training run.
