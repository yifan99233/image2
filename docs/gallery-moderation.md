# Gallery moderation

User publication is a request. `GET /gallery` requires a successful, undeleted
task in the current site with an output URL, `is_gallery_featured = true`, and a
non-null `gallery_featured_by`. Only the authorized admin endpoint can assign
the reviewer. User withdrawal clears the reviewer, so resubmission needs review.

The existing two columns encode the workflow without a schema migration:

| Requested (`is_gallery_featured`) | Reviewer (`gallery_featured_by`) | API review status |
| --- | --- | --- |
| false | null | none |
| true | null | pending |
| true | admin ID | approved |
| false | admin ID | rejected (including admin takedown) |

The raw database boolean alone must never be used as permission to publish.
Historical user recommendations become pending automatically; no originals are
deleted. Previous admin selections retain their approval. Withdrawn and deleted
works cannot be approved by a stale review request. Review operations lock the
task row, enforce admin permissions/site scope, and write audit records. Rejection
and takedown require a reason. A rejected author can resubmit for human review.

Admin task filters accept `gallery_review_status=pending|approved|rejected|none`
and combine with existing task status, user, keyword, and pagination filters.
`approved` matches actual public visibility; deleted records are omitted from
moderation filters. Admin and user responses expose the interpreted review status.

The initial production hotfix used `4c67960`, based on the then-running
`6388a8b`, in `/data/workspace/image2-gallery-review` to avoid releasing VIP
billing early. On 2026-10-12, the user subsequently authorized VIP production
release. The four app services now run the main-branch application at
`1289310` from `/data/workspace/image2`, including this moderation fix and VIP
billing. The old hotfix checkout is retained only as release history; it must
not be redeployed over fractional accounting. Public API verification after
the VIP release returned five admin-approved works and hid 18 pending works.
Do not roll the public API back to a version that allows self-publication.
