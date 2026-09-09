# SQLite as an application store

SQLite writes to a single file and runs in the calling process, which removes an entire
class of deployment problem at the cost of an entire class of scaling option. Write-ahead
logging allows one writer alongside many readers, which is usually the shape a desktop
application needs.

Foreign keys are off by default and must be enabled per connection, which surprises
developers who assume declared constraints are enforced constraints.

For vector search at modest scale a brute-force scan over stored vectors is often faster
than maintaining an index, because the index cost is paid on every write and the scan cost
only on query.
