# Ingest error codes

ERR_CHUNK_7742 is raised when a document produces no chunks after splitting. The usual
cause is a file whose extractable text falls below the minimum chunk length, which happens
with scanned pages carrying no text layer and with slide decks that are almost entirely
images.

ERR_EMBED_5130 indicates the embedding endpoint returned a vector of unexpected width. A
corpus indexed at one width cannot be searched at another, so the store refuses rather
than comparing incomparable vectors.

ERR_CORPUS_0091 means the corpus contains only auto-saved reports. Generated reports are
never used as evidence for new research, so a corpus holding nothing else has nothing to
retrieve.
