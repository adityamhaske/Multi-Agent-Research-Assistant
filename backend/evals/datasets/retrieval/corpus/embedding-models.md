# Choosing an embedding model

An embedding model maps text to a vector so that similar meanings land near each other.
Dimension is the obvious parameter and rarely the important one; what usually decides
retrieval quality is what the model was trained to consider similar, and whether that
matches the queries a corpus will actually receive.

Symmetric and asymmetric use differ. A model trained to match a short query against a long
passage behaves differently from one trained to match two sentences, and using the wrong
one produces retrieval that is confidently mediocre.

Changing model invalidates an index. Vectors from two models are not comparable even at
identical width, so a change means re-embedding everything.
