# Select the ids of comments this run should delete before posting fresh ones.
#
# Inputs:
#   $marker         this reviewer's scoped marker -- only its own comments
#   $legacy_marker  the pre-scoping shared marker
#   $sweep_legacy   whether to also clear unscoped comments left by older runs
#
# Only Bot-authored comments are eligible: a human quoting a marker must never
# have their comment deleted.
.[]
| select(
    .user.type == "Bot"
    and (
      (.body | contains($marker))
      or ($sweep_legacy and (.body | contains($legacy_marker)))
    )
  )
| .id
