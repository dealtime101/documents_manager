from django.db import models


# The closed lists live at module level, so that the model's choices AND the database constraints (built in each Meta, which
# cannot see the names of its enclosing class) come from ONE definition: adding a value here changes both.
class ScanState(models.TextChoices):
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class ItemState(models.TextChoices):
    PENDING = "pending"
    APPROVED = "approved"
    IGNORED = "ignored"
    REMOVED = "removed"


class EngineStatus(models.TextChoices):
    """What the engine proposes for a document (docflow.pipeline.Proposal.status)."""
    AUTO = "auto"
    CONFIRM = "confirm"
    MANUAL = "manual"
    DUPLICATE = "duplicate"
    LOGICAL_DUPLICATE = "logical_duplicate"
    ERROR = "error"


class ScanJob(models.Model):
    """A background scan. State lives in the database (not in memory): several gunicorn processes share it."""

    State = ScanState

    # a closed list, enforced by the database too (CHECK below): a typo cannot leave a scan shown as running forever
    state = models.CharField(max_length=10, choices=State.choices, default=State.RUNNING)
    total = models.IntegerField(default=0)
    done = models.IntegerField(default=0)
    created = models.IntegerField(default=0)
    skipped = models.IntegerField(default=0)
    error = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # enforced by the database, so it holds across gunicorn workers: at most ONE scan can be running
            models.UniqueConstraint(fields=["state"], condition=models.Q(state=ScanState.RUNNING), name="one_running_scan"),
            models.CheckConstraint(condition=models.Q(state__in=ScanState.values), name="scan_state_is_known"),
            # the progress figures: never negative, and never more done than to do, nor more created than done
            models.CheckConstraint(condition=models.Q(total__gte=0, done__gte=0, created__gte=0, skipped__gte=0),
                                   name="scan_counters_not_negative"),
            models.CheckConstraint(condition=models.Q(done__lte=models.F("total"), created__lte=models.F("done")),
                                   name="scan_counters_in_order"),
        ]


class Item(models.Model):
    """A document from the Inbox and what the engine intends to do with it. Nothing is moved until it is approved."""

    State = ItemState
    EngineStatus = EngineStatus  # the module-level class, under the name the code uses (Item.EngineStatus)

    PENDING, APPROVED, IGNORED, REMOVED = State.PENDING, State.APPROVED, State.IGNORED, State.REMOVED  # as used all over

    source_path = models.TextField()
    sha256 = models.CharField(max_length=64, db_index=True)
    # a closed list, enforced by the database too (CHECK below), like `state`: "confrim" would silently leave every filter
    engine_status = models.CharField(max_length=20, choices=EngineStatus.choices)
    # a closed list for forms and the admin (choices) AND for the database itself (the CHECK below): a typo such as
    # "aproved" is refused instead of silently making the item vanish from every filter
    state = models.CharField(max_length=10, choices=State.choices, default=State.PENDING, db_index=True)
    analysis = models.JSONField(null=True)                      # Analysis (fields + per-field scores)
    original = models.JSONField(null=True)                      # what the engine had detected (used for learning)
    final_name = models.TextField(blank=True, default="")
    rel_dir = models.TextField(blank=True, default="")          # destination relative to library_root
    confidence = models.FloatField(default=0.0)
    header = models.TextField(blank=True, default="")
    extraction = models.CharField(max_length=20, blank=True, default="")
    notes = models.JSONField(default=list)
    result_path = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True)
    # size and mtime of the file when it was hashed: a rescan trusts an unchanged file instead of reading it again
    source_size = models.BigIntegerField(null=True)
    source_mtime_ns = models.BigIntegerField(null=True)

    class Meta:
        ordering = ["-confidence", "id"]
        indexes = [
            # the queue reads the items of ONE state in this very order: the index serves the filter and the sort, no temporary sort
            models.Index(fields=["state", "-confidence", "id"], name="item_state_conf_idx"),
        ]
        constraints = [
            # one open proposal per file content at a path: a rescan (or two at once) can never double it
            models.UniqueConstraint(fields=["source_path", "sha256"], condition=models.Q(state=ItemState.PENDING),
                                    name="one_pending_item_per_file_content"),
            models.CheckConstraint(condition=models.Q(state__in=ItemState.values), name="item_state_is_known"),
            models.CheckConstraint(condition=models.Q(engine_status__in=EngineStatus.values), name="item_engine_status_is_known"),
        ]


class ItemText(models.Model):
    """The whole text read from a document, kept (in this local database only) so the filed archive can be searched. A separate
    table: the queue and the dashboard read thousands of items and must not drag every document's text along with them.
    The full-text index over it (item_fts) is built by the migration and kept in step by triggers."""

    item = models.OneToOneField(Item, primary_key=True, on_delete=models.CASCADE, related_name="fulltext")
    text = models.TextField(blank=True, default="")
