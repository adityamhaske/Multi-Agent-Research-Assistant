# Attention and the end of recurrence

Sequence models were built on recurrence for years: each position was processed after the
one before it, and information travelled along a chain. That serialisation was the
bottleneck. Attention replaced it by letting every position consult every other position
directly, in one parallel operation, so the path length between any two tokens became
constant instead of linear in their distance.

The cost is quadratic in sequence length, since every position attends to every other.
That trade — parallelism and short paths, paid for in quadratic compute — is why the
architecture displaced recurrent networks for long-range dependencies.

Positional information has to be injected explicitly, because attention alone is
permutation invariant and would otherwise treat a sentence as a bag of words.

Multiple heads exist because one attention pattern has to commit. A single head averages
over everything it attends to, so a model that needs both syntactic agreement and topical
similarity in the same layer cannot express them at once. Splitting the representation
lets separate heads specialise and the outputs be recombined.

The quadratic cost has produced a long line of approximations: windowed attention,
low-rank projections, and kernel formulations that avoid materialising the full matrix.
Each buys length by giving up something the exact form provides, and which loss is
acceptable depends entirely on whether long-range dependencies matter for the task.

Normalisation placement turned out to matter more than expected. Applying it before the
sublayer rather than after made deep stacks trainable without a warmup schedule, which is
a small change to the diagram and a large one to what can be trained.
