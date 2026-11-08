# Switchover from GlassFrog

The steps of the day GlassFrog stops being the source of truth. Delete
this file afterwards (the last step).

Open proposals imported from GlassFrog continue here: those published
async are adopted at their GlassFrog deadline (or when everybody else
consented here), those waiting for a meeting stay on the list for the
next governance meeting. Nobody resubmits them. What switches the app
over is removing `GLASSFROG_TOKEN` (`Proposal.decided_in_glassfrog`):
while it's set, the app leaves imported proposals to GlassFrog, which the
nightly import mirrors.

1. **Freeze GlassFrog**: tell everybody that from now on proposals,
   responses and assignments happen in the app only. Questions and
   consents given in GlassFrog to open proposals don't carry over (the
   deadline doesn't need them); a member who wants a meeting for one
   requests it in the app.
2. **Final import**, in the web pod (`kubectl -n prod get pods`,
   `governance-…` without `-import-`, `-fairy-`, `-end-` or `-migrate-`):

   ```
   kubectl -n prod exec $POD -c governance -- .venv/bin/python manage.py import_glassfrog --api
   ```

   Check its output and an open proposal in the app.
3. **Stop the import**, together (in `~/projects/argocd`):
   - remove the cron job `governance-import-glassfrog` from
     `governance/values.yaml`,
   - remove `GLASSFROG_TOKEN` from `secrets/governance-env` and load it
     (`fl secrets.load secrets/governance-env`),
   - deploy, then restart the pods so that they read the secret
     (`kubectl -n prod rollout restart deployment governance`).

   From now on the nightly `fairy_tasks` adopts imported proposals whose
   deadline passed, also any which passed since the final import.
4. **The handbook's links**: on the branch of feinheit/handbuch#126
   (`governance` in `~/projects/handbuch`), point the remaining links to
   GlassFrog to the app (`gov` 0.8.0 or later):

   ```
   gov export --json | python3 -I scripts/governance_links.py source
   ```

   It lists links whose text doesn't contain the current name (most are
   descriptive, like "hier"), archived and unknown ones. Check those and
   `git diff`, remove the script, commit, push and merge the pull
   request.
5. **Backup**: on the fetcher's server, run `scripts/fetch_backup.py`
   daily (with a read-only API token of the app) into a new repository
   instead of `scripts/fetch_glassfrog.py`. To consider then or
   afterwards: converting the GlassFrog export's commits into the
   backup's format.
6. **Cancel GlassFrog** once the app's first adoptions went through.
7. **Clean up the code** (one commit): remove "Until the switchover"
   from `docs/README.md` and `docs/README.de.md`, the notes about
   GlassFrog being the source of truth and the nightly import in
   `AGENTS.md` and `SPEC.md`, the switchover item of `SPEC.md`'s backlog,
   and this file. `Proposal.decided_in_glassfrog` and the importer may
   stay (the import of the whole history uses the export, not the
   token) or go.
