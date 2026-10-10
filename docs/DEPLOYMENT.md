# Deployment and recovery

The supported starting point is a local, single-user showcase. The comparison stack,
the first lesson, and the example-data experience serve different purposes; choose
one before starting services. Recorded example outputs are for exploring the UI.
Use the live lesson to verify model execution.

## Local data ownership

The lesson keeps its Pixeltable home in `data/lesson/pixeltable` and uploaded source
files in `data/lesson/uploads`. The full comparison uses its own stores. Keep the
catalog, uploaded files, and any upload receipts together when moving or backing
up an installation. Preserve the same media paths, or deliberately migrate them
and verify playback before using the restored catalog.

Use one writer for each local Pixeltable home. Do not start another service or
container against the same PostgreSQL data directory. The [Pixeltable operations
guide](https://docs.pixeltable.com/howto/deployment/operations) describes the
supported topology. More HTTP workers require an explicit deployment design.
The receipt store requires POSIX file locking (macOS or Linux). Native Windows
operation is outside this local intake contract.

## Before accepting other people's recordings

Put authentication and authorization on an application server or reverse proxy.
Protect upload, search, comments, deletion, and media playback together. A secret
placed in a browser bundle is available to its users. Keep provider credentials
on the server and redact them from logs.

Set request-body and media-duration limits, bound concurrent work, and choose a
retention period for recordings, transcripts, comments, and upload receipts.
Document who may read or delete each recording. Test an unauthorized request and
a cross-user media request before exposing the service. End-user identity and
tenant isolation are deployment responsibilities.

Keep the daemon and database private; expose only the application endpoints over
HTTPS. Use health checks for model readiness as well as service connectivity.
Record disk pressure, pending uploads, failed computations, and search readiness.

## Cold backup and restore drill

For a small local installation, a stopped copy is a simple recovery procedure:

1. Pause uploads and stop the application's service and its dedicated daemon.
   For the lesson, use `./scripts/run_pixeltable.sh stop`. Confirm that both the
   application and its embedded PostgreSQL database have stopped cleanly before
   copying database files; application exit alone is insufficient. Check the
   owned `pgdata` and database process, and use its management commands if it is
   still running. Do not stop an unrelated daemon or database.
2. Copy the entire application-owned Pixeltable home, source upload directory,
   and receipt store to access-controlled storage outside the working directory.
   Keep the deployed commit, lockfiles, environment variable names, and media
   path mapping with the backup. Store secret values separately.
3. Restore into an isolated location with matching dependencies and unused
   ports. Keep writes and model calls disabled during initial inspection.
4. Verify call IDs, transcript segments, comments and their anchors, media
   playback, and pending/failed receipt states. Verify search separately from
   transcription. Then allow the recovery worker to reconcile accepted uploads.
5. Compare those observations with the backup manifest before directing traffic
   to the restored service. Delete the drill copy according to the retention
   policy.

Never copy a running PostgreSQL data directory as a backup. For online database
backups and hosted storage, follow the [Pixeltable backup
guide](https://docs.pixeltable.com/howto/deployment/security) and include externally
stored source media. Table history does not replace a recoverable backup.

## Verification boundary

Automated upload recovery tests establish the tested single-writer behavior.
They do not establish public authentication, multi-tenant isolation, operator
response times, or restoration of a particular deployment. Record a completed
restore drill for the environment before claiming those guarantees. The local
LLM smoke previously failed under memory pressure; successful transcription
alone does not establish successful enrichment or searchable results.
