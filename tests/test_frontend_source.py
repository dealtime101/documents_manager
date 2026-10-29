"""Source-level checks on the React components (there is no JS test runner: these read the files themselves)."""
import re
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parents[1] / "frontend" / "src" / "components" / "ui"


def test_a_badge_only_reacts_to_the_pointer_when_it_is_a_link():
    """A Badge is a static <span> unless rendered as a link: a hover effect on every variant makes a plain label look clickable."""
    source = (UI / "badge.tsx").read_text(encoding="utf-8")
    variants = source[source.index("variants:"):source.index("defaultVariants")]
    classes = re.findall(r"[\w\[\]/:.\-]+", variants)
    hovers = [c for c in classes if "hover:" in c]
    assert hovers, "the variants lost every hover class: the check below would pass for nothing"
    assert [c for c in hovers if "[a]:hover:" not in c] == []             # "dark:[a]:hover:…" stacks, so "contains"


BITS = Path(__file__).resolve().parents[1] / "frontend" / "src" / "components" / "Bits.tsx"


def _status_badge(source: str) -> str:
    return source[source.index("export function StatusBadge"):source.index("const FIELDS")]


def test_a_long_status_label_is_cut_with_an_ellipsis_and_stays_readable_in_the_title():
    badge = _status_badge(BITS.read_text(encoding="utf-8"))
    assert 'className="truncate"' in badge and "title={label}" in badge     # visible cut + the whole text on hover
    assert "min-w-0" in badge and "shrink " in badge                         # it may shrink instead of pushing the % out
    assert "max-w-full" in (UI / "badge.tsx").read_text(encoding="utf-8")


def test_history_shows_a_load_error_through_the_translator_not_as_a_raw_exception_string():
    page = (BITS.parents[1] / "pages" / "History.tsx").read_text(encoding="utf-8")
    assert "setLoadError(errorText(e))" in page and "msg(loadError)" in page   # the raw server text goes through msg() when shown
    assert "setNote(String(" not in page                                     # "Error: HTTP error: 500" is not a text msg() knows


def test_history_says_no_operations_only_after_a_load_that_succeeded_and_came_back_empty():
    page = (BITS.parents[1] / "pages" / "History.tsx").read_text(encoding="utf-8")
    assert "useState<Operation[] | null>(null)" in page                      # "not loaded yet" is its own state
    assert "ops?.length === 0" in page and "ops.length === 0" not in page.replace("ops?.length === 0", "")
    assert "common.loading" in page


def test_history_names_an_undone_operation_in_words_and_keeps_its_text_readable():
    page = (BITS.parents[1] / "pages" / "History.tsx").read_text(encoding="utf-8")
    assert "t('hist.undone')" in page                                        # a word, not only a strike-through
    assert "text-slate-400" not in page                                      # 2.6:1 on white; slate-500 is 4.8:1


def test_each_history_undo_button_names_its_operation_and_the_action_column_has_a_header():
    page = (BITS.parents[1] / "pages" / "History.tsx").read_text(encoding="utf-8")
    assert "aria-label={t('hist.undoOp'" in page                             # "Undo operation 12 (file.pdf)", not 12 × "Undo"
    assert "<th />" not in page and "hist.actions" in page                   # an empty header names nothing


def test_history_messages_go_through_the_shared_live_regions():
    page = (BITS.parents[1] / "pages" / "History.tsx").read_text(encoding="utf-8")
    assert "<Notice note=" in page                                           # polite for a success, assertive for a failure
    assert 'className="rounded bg-slate-100' not in page                     # the old bare paragraph, announced by nothing


def test_history_shows_from_and_to_in_the_same_format_and_splits_on_both_separators():
    page = (BITS.parents[1] / "pages" / "History.tsx").read_text(encoding="utf-8")
    assert page.count("<PathCell path=") == 2                                # one component for both columns
    paths = (BITS.parents[1] / "paths.ts").read_text(encoding="utf-8")
    assert r"split(/[\\/]/)" in paths and r"lastIndexOf('\\')" in paths      # '/' and the Windows '\'


def test_history_allows_one_undo_at_a_time():
    page = (BITS.parents[1] / "pages" / "History.tsx").read_text(encoding="utf-8")
    assert "disabled={undoing !== null}" in page and "if (undoing !== null" in page   # the button AND the handler refuse a second one
    assert page.index("setUndoing(id)") < page.index("await api.undo(id)") < page.index("setUndoing(null)")


def test_the_app_shows_a_loading_status_instead_of_a_blank_page_while_the_session_is_checked():
    app = (BITS.parents[1] / "App.tsx").read_text(encoding="utf-8")
    assert "if (auth === null) return null" not in app
    assert "role=\"status\"" in app and "t('common.loading')" in app


def test_the_title_of_the_document_follows_the_page_shown():
    # DOC534.128: every page had the same title: Back / Forward entries, bookmarks and screen readers could not tell them apart
    import re
    app = (UI.parents[1] / "App.tsx").read_text(encoding="utf-8")
    route = (UI.parents[1] / "route.ts").read_text(encoding="utf-8")
    pages = re.search(r"export type Page = ([^\n]+)", route).group(1)
    names = dict(re.findall(r"(\w+): 'nav\.(\w+)'", app[app.index("const PAGE_NAME"):app.index("const MAX_SETUP_TRIES")]))
    assert set(names) == set(re.findall(r"'(\w+)'", pages)) and all(k == v for k, v in names.items())   # every page has its own name
    assert "document.title = `${t(PAGE_NAME[page])} \\u00b7 ${t('app.title')}`" in app and "}, [page, t])" in app


def test_saving_the_settings_leaves_the_screen_only_at_the_end_of_the_first_set_up():
    # DOC534.127: every save sent the user to the queue: changing several settings meant coming back to the tab each time
    settings = (UI.parents[1] / "pages" / "Settings.tsx").read_text(encoding="utf-8")
    save = settings[settings.index("const save = async"):settings.index("return (\n    <Card>")]
    assert "if (first) onSaved()" in save and "\n      onSaved()" not in save
    assert save.index("if (first) onSaved()") < save.index("setFirst(false)")        # read before it is cleared
    assert "onSaved={() => go({ page: 'queue', group: null })}" in (UI.parents[1] / "App.tsx").read_text(encoding="utf-8")   # the first set-up still goes to the queue


def test_the_first_run_check_counts_as_done_only_once_the_server_answered_and_is_tried_again():
    # DOC534.126: checkedSetup was set before the call: a failure meant the Settings screen never opened on a first run, silently
    app = (UI.parents[1] / "App.tsx").read_text(encoding="utf-8")
    effect = app[app.index("const [checkedSetup, setCheckedSetup]"):app.index("if (failure) {")]
    assert effect.index("api.settings().then(") < effect.index("setCheckedSetup(true)")                  # set in the answer, not before the call
    assert effect.count("setCheckedSetup(true)") == 1
    assert "window.location.hash = toHash({ page: 'settings', group: null })" in effect and "'#settings'" not in effect   # the route, not a hard-coded hash
    assert "console.warn('first-run check of the settings failed:', errorText(e))" in effect                # the failure leaves a trace
    assert "setupTries < MAX_SETUP_TRIES" in effect and "setTimeout(() => setSetupTries((n) => n + 1), SETUP_RETRY_MS)" in effect
    assert "return () => { cancelled = true; clearTimeout(timer) }" in effect and "[auth, checkedSetup, setupTries]" in effect


def test_an_error_of_the_extra_folders_names_its_line_and_is_tied_to_the_box():
    # DOC534.125: the box had no aria-invalid / aria-describedby and the message did not say which of the lines was refused
    got = _node_route("""({ plain: [m.lineOfEntry('a\\nb\\nc', 0), m.lineOfEntry('a\\nb\\nc', 2)],
                         blanks: [m.lineOfEntry('\\n\\n/x\\n  \\n/y\\n', 0), m.lineOfEntry('\\n\\n/x\\n  \\n/y\\n', 1)],
                         none: [m.lineOfEntry('a', 3), m.lineOfEntry('', 0), m.lineOfEntry('a', NaN)] })""", module="paths")
    assert got == {"plain": [1, 3], "blanks": [3, 5], "none": [None, None, None]}      # the 2nd entry sent is on line 5 of the box
    settings = (UI.parents[1] / "pages" / "Settings.tsx").read_text(encoding="utf-8")
    assert "aria-invalid={extraErrors.length ? true : undefined}" in settings and "aria-describedby={extraErrors.length ? 'err-extra-inboxes' : undefined}" in settings
    assert '<div id="err-extra-inboxes">' in settings and "t('settings.line', { n: line })" in settings and "lineOfEntry(v.extra," in settings
    i18n = (UI.parents[1] / "i18n.tsx").read_text(encoding="utf-8")
    assert "'settings.line': 'Line {n}:'" in i18n and "'settings.line': 'Ligne {n} :'" in i18n


def test_the_folder_picker_cannot_go_up_from_the_root():
    # DOC534.124: at the root the parent is the root itself (or empty, which reloads the default folder): "Up" did nothing useful
    settings = (UI.parents[1] / "pages" / "Settings.tsx").read_text(encoding="utf-8")
    assert "disabled={!list.parent || list.parent === list.path}" in settings and "onClick={() => setTarget(list.parent)}>{t('settings.up')}" in settings
    # what the server answers at the roots: the parent of a root is the root (POSIX) and the drive root keeps its backslash (Windows)
    from pathlib import Path, PureWindowsPath
    assert str(Path("/").parent) == "/" and str(PureWindowsPath("C:\\").parent) == "C:\\"


def test_a_new_save_of_the_settings_clears_the_saved_message_of_the_previous_one():
    # DOC534.122: after a first good save, a refused one showed its field errors beside the green "saved"
    settings = (UI.parents[1] / "pages" / "Settings.tsx").read_text(encoding="utf-8")
    save = settings[settings.index("const save = async"):settings.index("return (\n    <Card>")]
    assert save.index("setNote(null)") < save.index("await api.saveSettings(") < save.index("setNote({ ok: true")      # cleared first, set on success only
    assert save.index("setErrors({})") < save.index("await api.saveSettings(")


def test_the_fixed_extension_of_a_file_name_field_is_read_by_screen_readers_with_the_field():
    # DOC534.121: the extension was aria-hidden: nobody using a screen reader learned that it is added by the program
    bits = BITS.read_text(encoding="utf-8")
    name_input = bits[bits.index("export function NameInput"):bits.index("export function Notice")]
    assert "aria-hidden" not in name_input                                                                        # the extension box is no longer hidden
    assert "aria-describedby={ext ? extId : undefined}" in name_input and "<span id={extId}" in name_input         # tied to the field
    assert "<span className=\"sr-only\">{t('field.extAdded')} </span>{ext}" in name_input                          # and says what it is
    i18n = (BITS.parents[1] / "i18n.tsx").read_text(encoding="utf-8")
    assert "'field.extAdded': 'Extension added automatically:'" in i18n and "'field.extAdded': \"Extension ajoutée automatiquement :\"" in i18n


def test_the_rules_screen_locks_a_change_with_a_ref_read_at_once_not_with_a_state_one_render_late():
    # DOC534.120: two clicks before the re-render both read busy=false and started two requests
    rules = (UI.parents[1] / "pages" / "Rules.tsx").read_text(encoding="utf-8")
    act = rules[rules.index("const act = "):rules.index("const dropDraft")]
    assert "const working = useRef(false)" in rules
    assert "if (working.current) return" in act and "if (busy) return" not in act
    assert act.index("if (working.current) return") < act.index("working.current = true") < act.index("setBusy(true)")   # taken at once
    assert act.rindex("working.current = false") > act.index("finally")                                                    # always let go
    assert "setBusy(true)" in act and "setBusy(false)" in act                                                              # `busy` still drives the buttons


def test_forgetting_a_route_also_forgets_the_unsaved_typing_for_that_company():
    # DOC534.119: the draft stayed in memory: when the company was learned again the field showed the old typing, not the destination
    rules = (UI.parents[1] / "pages" / "Rules.tsx").read_text(encoding="utf-8")
    assert "const dropDraft = (company: string) => setDrafts(" in rules and "delete next[company]" in rules
    forget = rules[rules.index("const forget = "):rules.index("const saveRoute = ")]
    assert "kind === 'route' ? () => dropDraft(company) : undefined" in forget            # only a route has a draft
    assert "() => dropDraft(company))" in rules[rules.index("const saveRoute = "):]       # and saving still clears it, as before


def test_a_failed_background_refresh_is_quiet_only_when_numbers_are_already_on_screen():
    # DOC534.118: the tab became visible during the first load, the quiet request replaced it and failed: "Loading" for ever, no error
    page = (UI.parents[1] / "pages" / "Dashboard.tsx").read_text(encoding="utf-8")
    assert "const shown = useRef(false)" in page and "shown.current = true" in page
    assert "if (quiet && shown.current) setStale(true)" in page and "else setErr(errorText(e))" in page
    assert page.index("shown.current = true") < page.index("if (quiet && shown.current)")


def test_the_launcher_token_stays_in_the_address_while_the_server_cannot_be_reached_and_retry_signs_in_again():
    # DOC534.34: the token was removed from the URL even when the sign-in failed for lack of a network answer, and "Retry" only
    # re-checked the session: the user stayed "not signed in" until the desktop application was started again
    app = (BITS.parents[1] / "App.tsx").read_text(encoding="utf-8")
    start = app[app.index("const start = async () => {"):app.index("useEffect(() => { void start()")]
    assert "e instanceof ApiError && e.status === undefined) throw e" in start                   # no network answer: the failure is shown
    assert start.index("e.status === undefined") < start.index("window.history.replaceState")     # the address is cleaned after, not before
    assert "setFailure(''); void start()" in app and "setFailure(''); refresh()" not in app        # Retry runs the whole start again


def test_the_release_notes_ignore_a_late_answer_for_a_language_left_and_forget_an_old_failure():
    # DOC534.44: after a failure the error stayed for ever, and a quick language switch let the slower answer win
    notes = (BITS.parents[1] / "pages" / "Notes.tsx").read_text(encoding="utf-8")
    effect = notes[notes.index("useEffect(() => {"):notes.index("}, [lang])")]
    assert "let cancelled = false" in effect and "return () => { cancelled = true }" in effect
    assert "if (!cancelled) { setReleases(rows); setError('') }" in effect                  # the answer is used only if still wanted
    assert "if (!cancelled) setError(errorText(e))" in effect                                 # and so is the failure


def test_every_tab_has_a_tabpanel_inside_the_same_tabs_root():
    app = (BITS.parents[1] / "App.tsx").read_text(encoding="utf-8")
    assert app.count("<Tabs ") == 1 and app.count("</Tabs>") == 1            # one root around the tab list AND the pages
    for page in ("dashboard", "queue", "history"):
        assert f'<TabsTrigger value="{page}">' in app and f'<TabsContent value="{page}"' in app


NODE_TIMEOUT = 30  # seconds: these scripts transpile one file and print a line


def run_node(command: list[str], **kwargs):
    """subprocess.run for node with its own short limit; a node that never ends (a promise that is never settled, a missing module
    waiting) is a failure that says so, not a frozen suite (DOC534.225)."""
    import subprocess

    import pytest
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=NODE_TIMEOUT, **kwargs)
    except subprocess.TimeoutExpired:
        pytest.fail(f"node did not finish within {NODE_TIMEOUT} s: {' '.join(command[:2])} ...", pytrace=False)


def test_a_node_that_never_ends_fails_the_test_with_a_message(monkeypatch):
    # DOC534.225: no node call had a limit; a promise never settled held the whole suite
    import shutil

    import pytest
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available")
    monkeypatch.setitem(globals(), "NODE_TIMEOUT", 1)
    with pytest.raises(pytest.fail.Exception, match="node did not finish within 1 s"):
        run_node([node, "-e", "setInterval(() => {}, 1000)"])
    assert run_node([node, "-e", "console.log(1)"]).stdout.strip() == "1"                 # and a normal run is untouched


def _node_route(expression: str, module: str = "route", setup: str = ""):
    """Run frontend/src/route.ts itself (transpiled with the project's own TypeScript), so the URL logic is tested, not read."""
    import json
    import shutil

    import pytest
    node = shutil.which("node")
    frontend = BITS.parents[2]
    typescript = frontend / "node_modules" / "typescript" / "lib" / "typescript.js"
    if not node or not typescript.exists():
        pytest.skip("node or the frontend's node_modules is not available")
    code = f"""
      const ts = require({json.dumps(str(typescript))});
      const src = require('fs').readFileSync({json.dumps(str(frontend / "src" / (module + ".ts")))}, 'utf8');
      const js = ts.transpileModule(src, {{ compilerOptions: {{ module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 }} }}).outputText;
      {setup}
      import('data:text/javascript;base64,' + Buffer.from(js).toString('base64')).then(async (m) => console.log(JSON.stringify(await ({expression}))));
    """
    done = run_node([node, "-e", code])
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_url_hash_names_the_page_and_the_queue_category_and_falls_back_to_the_queue():
    got = _node_route("""{
      queue: m.parseHash(''), history: m.parseHash('#history'), slash: m.parseHash('#/dashboard'),
      group: m.parseHash('#queue/duplicates'), junkGroup: m.parseHash('#queue/nope'), junkPage: m.parseHash('#nonsense'),
      groupOnAnotherPage: m.parseHash('#history/duplicates'),
      write: [m.toHash({page: 'queue', group: 'errors'}), m.toHash({page: 'history', group: null})] }""")
    assert got["queue"] == {"page": "queue", "group": None}
    assert got["history"] == {"page": "history", "group": None} and got["slash"]["page"] == "dashboard"
    assert got["group"] == {"page": "queue", "group": "duplicates"}
    assert got["junkGroup"]["group"] is None and got["junkPage"] == {"page": "queue", "group": None}
    assert got["groupOnAnotherPage"] == {"page": "history", "group": None}      # a category only means something in the queue
    assert got["write"] == ["#queue/errors", "#history"]


def test_a_route_written_as_a_hash_is_read_back_as_the_same_route():
    # DOC534.175: {page: 'history', group: 'errors'} was written "#history/errors" and read back with no group
    got = _node_route("""(() => {
      const routes = [{page: 'queue', group: null}, {page: 'queue', group: 'errors'}, {page: 'history', group: 'errors'},
                      {page: 'dashboard', group: 'auto'}, {page: 'settings', group: null}]
      return routes.map((r) => [m.toHash(r), m.parseHash(m.toHash(r))]) })()""")
    assert got[2][0] == "#history" and got[3][0] == "#dashboard"                  # a group is written for the queue only
    assert [h for h, _ in got] == ["#queue", "#queue/errors", "#history", "#dashboard", "#settings"]
    assert [r for _, r in got] == [{"page": "queue", "group": None}, {"page": "queue", "group": "errors"}, {"page": "history", "group": None},
                                   {"page": "dashboard", "group": None}, {"page": "settings", "group": None}]


def test_the_app_follows_the_hash_and_navigation_writes_it():
    app = (BITS.parents[1] / "App.tsx").read_text(encoding="utf-8")
    assert "addEventListener('hashchange'" in app and "removeEventListener('hashchange'" in app
    assert "window.location.hash = toHash(route)" in app and "useState<Page>" not in app


def test_a_network_failure_reaches_the_screens_as_a_translatable_api_error_not_a_raw_typeerror():
    api = (BITS.parents[1] / "api.ts").read_text(encoding="utf-8")
    assert "throw new ApiError('Network error: the server cannot be reached.')" in api   # fetch's "Failed to fetch" never escapes
    assert "'Network error: the server cannot be reached.': 'Erreur réseau" in (BITS.parents[1] / "i18n.tsx").read_text(encoding="utf-8")


def test_a_disabled_input_can_show_its_not_allowed_cursor():
    source = (UI / "input.tsx").read_text(encoding="utf-8")
    assert "disabled:cursor-not-allowed" in source
    assert "disabled:pointer-events-none" not in source                      # it would stop the pointer reaching the field


def test_ui_components_get_cn_from_the_one_local_module():
    """src/lib/utils.ts is where the project chooses its class-merging helper (shadcn's own `cn` package today)."""
    assert (UI.parents[1] / "lib" / "utils.ts").read_text(encoding="utf-8").strip() == 'export { cn } from "cn"'
    direct = [p.name for p in UI.glob("*.tsx") if 'from "cn"' in p.read_text(encoding="utf-8")]
    assert direct == []                                                      # changing the helper is then a one-line change
    assert all('import { cn } from "@/lib/utils"' in p.read_text(encoding="utf-8") for p in UI.glob("*.tsx") if "cn(" in p.read_text(encoding="utf-8"))


def test_the_cn_helper_merges_conflicting_tailwind_classes_the_way_the_components_rely_on():
    """Components override each other's classes (TabsContent text-sm -> text-base, StatusBadge shrink-0 -> shrink)."""
    import json
    import shutil

    import pytest
    frontend = UI.parents[2]
    if not shutil.which("node") or not (frontend / "node_modules" / "cn").exists():
        pytest.skip("node or the frontend's node_modules is not available")
    code = ("import('cn').then(({cn}) => console.log(JSON.stringify([cn('px-2 py-1 text-sm', 'px-4 text-base'),"
            " cn('shrink-0', 'shrink'), cn('hover:bg-muted', 'hover:bg-primary', 'dark:hover:bg-muted/50'), cn('a', false, null, 'b')])))")
    done = run_node(["node", "-e", code], cwd=frontend)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == ["py-1 px-4 text-base", "shrink", "hover:bg-primary dark:hover:bg-muted/50", "a b"]


def test_the_language_switch_is_named_through_the_translator():
    source = (BITS.parents[1] / "i18n.tsx").read_text(encoding="utf-8")
    assert "aria-label={t('lang.label')}" in source and 'aria-label="Language"' not in source
    assert "'lang.label': 'Language'" in source and "'lang.label': 'Langue'" in source


def test_the_queue_has_one_live_region_that_is_never_unmounted():
    page = (BITS.parents[1] / "pages" / "Queue.tsx").read_text(encoding="utf-8")
    assert page.count("<Notice note={note} />") == 1                         # not one per branch: switching branches would re-create it
    assert page.index("<Notice note={note} />") < page.index("{current && form ? (")   # and it sits OUTSIDE the conditional


def test_the_state_and_group_filters_are_encoded_in_the_query_string():
    got = _node_route("""(async () => { await m.api.items('pending'); await m.api.items('a&b#c d', 'duplicates'); return seen })()""",
                      module="api", setup="""
      globalThis.document = { cookie: '' };
      globalThis.seen = [];
      globalThis.fetch = async (url) => { seen.push(url); return new Response('[]', { status: 200,
        headers: { 'content-type': 'application/json', 'X-Total-Count': '0' } }) };""")
    assert got[0] == "/api/items?state=pending"
    assert got[1] == "/api/items?state=a%26b%23c+d&group=duplicates"             # & and # no longer cut the query short


def test_every_loading_and_retry_text_comes_from_the_one_shared_pair_of_keys():
    keys = [k for k in re.findall(r"t\('([\w.]+)'", "".join(p.read_text(encoding="utf-8") for p in (UI.parents[1]).rglob("*.tsx")))
            if k.rsplit(".", 1)[-1] in ("loading", "retry")]
    assert keys and set(keys) == {"common.loading", "common.retry"}          # no second "Retry" / "Try again" wording


def test_file_names_and_folders_are_cut_on_both_separators():
    got = _node_route("""({ posix: [m.baseName('/a/b/c.pdf'), m.dirName('/a/b/c.pdf')],
      windows: [m.baseName('D:\\\\Docs\\\\Factures\\\\c.pdf'), m.dirName('D:\\\\Docs\\\\Factures\\\\c.pdf')],
      mixed: [m.baseName('C:/In\\\\x.pdf'), m.dirName('C:/In\\\\x.pdf')],
      bare: [m.baseName('c.pdf'), m.dirName('c.pdf')], root: [m.baseName('/c.pdf'), m.dirName('/c.pdf')] })""", module="paths")
    assert got["posix"] == ["c.pdf", "/a/b"] and got["windows"] == ["c.pdf", "D:\\Docs\\Factures"]
    assert got["mixed"] == ["x.pdf", "C:/In"] and got["bare"] == ["c.pdf", ""] and got["root"] == ["c.pdf", "/"]


def test_the_folder_of_a_file_at_the_root_of_a_drive_is_the_root_not_the_current_folder_of_the_drive():
    # DOC534.180: dirName('C:\\a.pdf') was 'C:', which Windows reads as "the current folder of drive C", while '/' was kept on POSIX
    got = _node_route("""({ backslash: m.dirName('C:\\\\a.pdf'), slash: m.dirName('c:/a.pdf'), deeper: m.dirName('C:\\\\Docs\\\\a.pdf'),
      posix: m.dirName('/a.pdf'), two: m.dirName('ab:\\\\a.pdf') })""", module="paths")
    assert got["backslash"] == "C:\\" and got["slash"] == "c:/" and got["deeper"] == "C:\\Docs"
    assert got["posix"] == "/" and got["two"] == "ab:"                              # only a single drive letter is a drive


def test_a_folder_written_with_a_trailing_separator_still_has_its_name():
    # DOC534.179: '/home/u/projet/' came back whole, the last segment being empty
    got = _node_route("""({ posix: m.baseName('/home/u/projet/'), windows: m.baseName('D:\\\\data\\\\'), several: m.baseName('/a/b//'),
      mixed: m.baseName('C:/In\\\\sub/'), root: [m.baseName('/'), m.baseName('//'), m.baseName('')] })""", module="paths")
    assert got["posix"] == "projet" and got["windows"] == "data" and got["several"] == "b" and got["mixed"] == "sub"
    assert got["root"] == ["/", "//", ""]                                         # nothing left to name: the path itself, as before


def test_field_keeps_an_id_the_caller_gave_its_input():
    source = BITS.read_text(encoding="utf-8")
    assert "children.props.id ?? generated" in source                        # the caller's id wins over the generated one
    assert "<Label htmlFor={id}>" in source and "cloneElement(children, { id })" in source   # label and input share THAT id


@pytest.mark.parametrize("name", ["card", "input", "label"])
def test_components_that_use_react_only_for_its_types_import_it_as_a_type(name):
    first = (UI / f"{name}.tsx").read_text(encoding="utf-8").splitlines()[0]
    assert first == 'import type * as React from "react"'                    # nothing of React is used at run time (new JSX transform)


def test_the_entry_point_checks_for_its_root_element_instead_of_asserting_it():
    main = (UI.parents[1] / "main.tsx").read_text(encoding="utf-8")
    assert "getElementById('root')!" not in main                              # a non-null assertion hides a missing element
    assert "if (!root) throw new Error(" in main and "createRoot(root)" in main


def test_every_queue_action_returns_the_message_it_shows():
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text(encoding="utf-8")
    assert "fn: () => Promise<string>" in queue and "string | void" not in queue   # tsc -b makes each caller return its text


def test_the_queue_save_action_takes_its_item_and_form_instead_of_asserting_them():
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text(encoding="utf-8")
    assert "const save = (item: Item, values: Form) =>" in queue and "onClick={() => save(current, form)}" in queue
    assert "api.save(item.id, payload(values))" in queue and "api.save(current!.id, payload(form!))); return" not in queue


def test_the_queue_approve_action_takes_its_item_and_form_and_saves_an_edit_first():
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text(encoding="utf-8")
    assert "const approve = (item: Item, values: Form) =>" in queue and "onClick={() => approve(current, form)}" in queue
    body = queue[queue.index("const approve = "):queue.index("const approveAuto")]
    assert body.index("api.save(item.id") < body.index("api.approve(item.id)")     # an edit is saved BEFORE the approval
    assert "!" not in re.sub(r"!==|!=|=>|\|\||&&|'[^']*'", "", body.split("=> run(")[0])   # and no non-null assertion in the signature


def test_the_queue_form_setter_updates_from_the_latest_state_without_an_assertion():
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text(encoding="utf-8")
    setter = queue[queue.index("const set = (k: keyof Form)"):queue.index("return (\n    // One column")]
    assert "setForm((f) => (f ? { ...f, [k]: value } : f))" in setter and "form!" not in setter
    assert "const value = e.target.value" in setter                          # read before the updater runs


def test_the_approval_message_is_built_from_a_list_of_sentences_not_by_concatenation():
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text(encoding="utf-8")
    body = queue[queue.index("const approve = "):queue.index("const approveAuto")]
    assert "const sentences = [t('queue.filed')]" in body and "sentences.join(' ')" in body
    assert "t('queue.filed') +" not in body


def test_the_font_licence_travels_with_the_font_files_the_interface_serves():
    """Geist is under the SIL Open Font License: bundling it in an application is allowed, provided each copy of the font
    comes with the copyright notice and the licence. The text is in public/, so the build copies it next to the fonts."""
    licence = (UI.parents[2] / "public" / "fonts-LICENSE-Geist-OFL-1.1.txt").read_text(encoding="utf-8")
    assert "SIL Open Font License, Version 1.1" in licence and "The Geist Project Authors" in licence
    package = (UI.parents[2] / "node_modules" / "@fontsource-variable" / "geist" / "LICENSE")
    if package.exists():
        assert licence == package.read_text(encoding="utf-8")                                  # it is the package's own text, not a rewrite


def test_the_queue_offers_tick_boxes_and_a_batch_approval_for_items_that_can_be_filed_as_they_stand():
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text(encoding="utf-8")
    # DOC474.144: not duplicates, not manual, not errors, AND with a name and a destination (the server refuses the others)
    assert "const approvable = (i: Item) => (i.status === 'auto' || i.status === 'confirm') && !!i.final_name && !!i.rel_dir" in queue
    assert "type=\"checkbox\"" in queue and "t('queue.tick'" in queue and "disabled={busy || !approvable(i)}" in queue
    assert "api.approveSelected(ticks.map((i) => i.id))" in queue and "confirm(t('queue.confirmBatch'" in queue
    assert "setTicked(new Set())" in queue                                                          # the selection does not outlive its approval
    api = (UI.parents[1] / "api.ts").read_text(encoding="utf-8")
    assert "'/api/items/approve-selected', { ids }" in api


def test_the_rules_screen_is_a_page_of_the_application_and_changes_only_learned_rules_with_confirmation():
    got = _node_route("({ rules: m.parseHash('#rules'), write: m.toHash({ page: 'rules', group: null }), groupIgnored: m.parseHash('#rules/duplicates') })")
    assert got["rules"] == {"page": "rules", "group": None} and got["write"] == "#rules"
    assert got["groupIgnored"] == {"page": "rules", "group": None}
    app = (UI.parents[1] / "App.tsx").read_text(encoding="utf-8")
    assert '<TabsTrigger value="rules">' in app and '<TabsContent value="rules"' in app
    page = (UI.parents[1] / "pages" / "Rules.tsx").read_text(encoding="utf-8")
    # forgetting asks first, and the question names the company (and the pattern) that would be forgotten (DOC474.243)
    assert "confirm(t('rules.confirmForget', { what: pattern ? `${company} / “${pattern}”` : company }))" in page
    assert "aria-label={pattern ? t('rules.forgetPatternLabel'" in page and ": t('rules.forgetLabel'" in page   # named, per pattern too
    assert "aria-label={t('rules.destinationOf'" in page                                                      # every control is named
    assert "<Notice note={shownNote} />" in page and "reloadError ?" in page   # results through the live regions (a failed reload too)
    api = (UI.parents[1] / "api.ts").read_text(encoding="utf-8")
    assert "'/api/rules/forget'" in api and "'/api/rules/route'" in api


def test_the_dashboard_shows_the_accuracy_card_with_the_observation_worded_as_one():
    card = (UI.parents[1] / "components" / "Accuracy.tsx").read_text(encoding="utf-8")
    assert "api.stats()" in card and "t('acc.suggest'" in card and "t('acc.noSuggest'" in card
    assert "aria-hidden=\"true\"" in card                                      # the bars are decoration: the numbers carry the meaning
    assert "<Accuracy />" in (UI.parents[1] / "pages" / "Dashboard.tsx").read_text(encoding="utf-8")
    source = (UI.parents[1] / "i18n.tsx").read_text(encoding="utf-8")
    assert source.count("This is an observation, not a guarantee") == 1 and source.count("pas une garantie") == 1


def test_a_file_name_is_typed_without_its_pdf_extension_which_is_fixed_and_greyed():
    src = UI.parents[1]
    bits = (src / "components" / "Bits.tsx").read_text(encoding="utf-8")
    assert "export function NameInput" in bits and 'className="flex select-none items-center rounded-r-md' in bits and "text-slate-500" in bits   # (DOC534.121: no aria-hidden)
    assert "stem + ext" in bits and "toLowerCase().endsWith(ext.toLowerCase())" in bits       # a typed ".pdf" is not doubled
    for page in ("Queue.tsx", "Library.tsx"):
        text = (src / "pages" / page).read_text(encoding="utf-8")
        assert "<NameInput" in text, page
    assert "onChange={set('final_name')}" not in (src / "pages" / "Queue.tsx").read_text(encoding="utf-8")      # no plain text field for the name any more


def test_the_library_explorer_page_asks_before_deleting_and_only_calls_its_own_endpoints():
    got = _node_route("({ read: m.parseHash('#library'), write: m.toHash({ page: 'library', group: null }) })")
    assert got["read"] == {"page": "library", "group": None} and got["write"] == "#library"
    src = UI.parents[1]
    page = (src / "pages" / "Library.tsx").read_text(encoding="utf-8")
    assert "api.library(path)" in page and "dangerouslySetInnerHTML" not in page
    used = set(re.findall(r"api\.(\w+)", page))
    assert used <= {"library", "libraryFileUrl", "librarySearch", "libraryNewFolder", "libraryRename", "libraryMove", "libraryDelete",
                    "libraryPlan", "libraryApply", "vocabulary", "destinations"}           # the explorer calls nothing else (no item, no scan)
    # a deletion is always confirmed first, in the page itself (DOC534.67: confirm() is not reliable in the desktop window)
    assert "confirm(" not in page and "<Confirm text={sentence(path)}" in page and "<Confirm text={sentence(file)}" in page
    assert "t(inTrash(target) ? 'library.confirmForever' : 'library.confirmTrash'" in page
    assert page.count("onClick={() => setConfirming(") == 2 and "onOk={() => remove(path)}" in page and "onOk={() => remove(file)}" in page   # the buttons only ask
    remover = page[page.index("const remove = "):page.index("const search = ")]
    assert "api.libraryDelete(target)" in remover and "confirm" not in remover.replace("setConfirming", "")
    api = (src / "api.ts").read_text(encoding="utf-8")
    assert "new URLSearchParams({ path })" in api and "new URLSearchParams({ q })" in api    # paths and queries are encoded, not concatenated
    assert '<TabsTrigger value="library">' in (src / "App.tsx").read_text(encoding="utf-8")


def test_a_proposal_read_for_one_library_file_never_fills_the_form_of_another():
    # DOC534.19: the list stays clickable while a document is read; the late answer for file A must not fill the form of file B
    page = (UI.parents[1] / "pages" / "Library.tsx").read_text(encoding="utf-8")
    assert "const shown = useRef(file)" in page and "shown.current = file;" in page       # what the form is about now
    assert "const asked = file" in page and "api.libraryPlan(asked)" in page              # what was asked, fixed at the click
    assert page.index("if (shown.current !== asked) return") > page.index("api.libraryPlan(asked)")   # checked after the wait, before filling
    assert "if (shown.current === asked) setProblem(errorText(e))" in page               # and an error for A is not shown on B


def test_a_poll_that_began_before_an_action_never_brings_back_the_list_as_it_was():
    # DOC534.71: a polled answer arriving after run()'s load() reinstalled the old list, which still held the document just filed
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text(encoding="utf-8")
    assert "const generation = useRef(0)" in queue
    tick = queue[queue.index("const tick = async () => {"):queue.index("timer = setTimeout(tick, 3000)\n    return")]
    assert tick.index("const started = generation.current") < tick.index("await api.scanStatus()")           # taken before any request
    assert tick.index("if (generation.current !== started)") < tick.index("setItems(list)")                  # and compared before the state is written
    load = queue[queue.index("const load = useCallback("):queue.index("}, [group])")]
    assert "generation.current += 1" in load.split("await api.items")[0]
    run = queue[queue.index("const run = async"):queue.index("const changed = ")]
    assert run.index("generation.current += 1") < run.index("setBusy(true)")


def test_the_scan_refresh_keeps_a_document_being_edited_even_when_it_left_the_list():
    # DOC534.20: the polled refresh dropped the open document (filed elsewhere), `dirty` fell back to false, and the next cycle replaced the form
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text(encoding="utf-8")
    tick = queue[queue.index("const tick = async () => {"):queue.index("timer = setTimeout(tick, 3000)\n    return")]
    assert "dirtyRef.current && selRef.current !== null && !fetched.some((i) => i.id === selRef.current)" in tick
    assert "itemsRef.current.find((i) => i.id === selRef.current)" in tick and "const list = edited ? [edited, ...fetched] : fetched" in tick
    assert tick.index("const list = edited") < tick.index("setItems(list)")          # the kept document is in the list that is shown


def test_the_library_apply_button_needs_a_preview_computed_for_what_is_typed_now():
    # DOC534.65: for 400 ms after an edit the old "will be" line stayed and Apply sent the NEW fields
    page = (UI.parents[1] / "pages" / "Library.tsx").read_text(encoding="utf-8")
    assert "const ready = !!plan?.final_name && !!plan?.rel_dir && planned === JSON.stringify([form, relDir, finalName])" in page
    assert "const asked = JSON.stringify([form, relDir, finalName])" in page and "setPlanned(asked)" in page   # what the plan was asked for
    assert "setPlanned(JSON.stringify([p.fields, '', '']))" in page                  # a proposal from the document is for its own fields
    assert "disabled={busy || !ready} onClick={apply}" in page and "{plan && ready &&" in page   # Apply AND the preview wait for it


def test_a_proposal_for_a_library_file_does_not_start_a_second_plan_request_for_the_same_inputs():
    # DOC534.66: after "Suggest" the form changed, the effect ran again and asked the server for the plan it had just been given
    page = (UI.parents[1] / "pages" / "Library.tsx").read_text(encoding="utf-8")
    effect = page[page.index("// the name and folder they give, recomputed shortly after each change"):page.index("const set = ")]
    assert "if (planned === asked) return" in effect and "[file, form, relDir, finalName, touched, planned]" in effect
    assert effect.index("if (planned === asked) return") < effect.index("api.libraryPlan(")   # before any request is scheduled
    assert "setPlan(null); setPlanned('')" in effect                                        # a failed plan is asked again for the same inputs


def test_the_folder_actions_of_the_library_wait_for_the_running_operation_like_the_file_actions():
    # DOC534.70: rename, move and delete of a folder stayed available while another change was running
    page = (UI.parents[1] / "pages" / "Library.tsx").read_text(encoding="utf-8")
    for action in ("setAsk('newFolder')", "setAsk('renameFolder')", "setMoving('folder')", "setConfirming(path)"):
        assert f'size="sm" disabled={{busy}} onClick={{() => {action}}}' in page, action
    assert 'size="sm" disabled={busy} onClick={() => setConfirming(file)}' in page            # the file's own delete already did


def test_the_move_picker_builds_paths_from_the_folder_its_list_was_read_for():
    # DOC534.69: while the next folder loaded (or after a failure) the old list was joined with the NEW path: a click led nowhere
    page = (UI.parents[1] / "pages" / "Library.tsx").read_text(encoding="utf-8")
    picker = page[page.index("function MovePicker"):page.index("function Classify")]
    assert "join(at, f)" not in picker and picker.count("join(list.path, f)") == 3
    assert "onClick={() => setAt(join(list.path, f))}" in picker


def test_the_search_screen_marks_the_words_found_as_elements_and_never_as_html():
    got = _node_route("({ search: m.parseHash('#search'), write: m.toHash({ page: 'search', group: null }) })")
    assert got["search"] == {"page": "search", "group": None} and got["write"] == "#search"
    page = (UI.parents[1] / "pages" / "Search.tsx").read_text(encoding="utf-8")
    assert "dangerouslySetInnerHTML" not in page and "<mark" in page                      # a snippet is document text: elements only
    assert 'role="status"' in page and 'role="alert"' in page                              # count and errors are announced
    assert "api.search(query)" in page and "aria-label={t('search.openLabel'" in page
    api = (UI.parents[1] / "api.ts").read_text(encoding="utf-8")
    assert "new URLSearchParams({ q })" in api                                             # the query is encoded, not concatenated
    assert '<TabsTrigger value="search">' in (UI.parents[1] / "App.tsx").read_text(encoding="utf-8")


def test_declining_the_bulk_confirmation_changes_nothing():
    # DOC474.31: the confirm() sits BEFORE run(), so a "Cancel" neither reloads the list nor resets the selection or the form
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text(encoding="utf-8")
    body = queue[queue.index("const approveSelected"):queue.index("const autoCount")]
    assert body.index("confirm(") < body.index("run(")
    assert "return ''" not in body


def test_bulk_approvals_ask_before_dropping_an_edit_and_keep_the_current_item():
    # DOC474.32: like select(), a bulk action confirms when the form is dirty, and reloads keeping the current item
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text(encoding="utf-8")
    for name, end in (("const approveAuto", "const approveSelected"), ("const approveSelected", "const autoCount")):
        body = queue[queue.index(name):queue.index(end)]
        assert "keepEdit()" in body and "run(" in body and ", sel)" in body, name
    assert "const keepEdit = () => !dirty || confirm(t('queue.confirmDiscard'))" in queue


def test_approve_automatic_goes_on_after_the_point_where_the_previous_press_stopped():
    # DOC534.57: pressing again retried the same failures first
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text(encoding="utf-8")
    body = queue[queue.index("const afterAuto = useRef(0)"):queue.index("const approveSelected")]
    assert "api.approveAuto(afterAuto.current)" in body and "afterAuto.current = r.remaining ? r.next_after ?? 0 : 0" in body
    assert "approveAuto: (after = 0) => call<Batch>('POST', '/api/items/approve-auto', { after }" in (UI.parents[1] / "api.ts").read_text(encoding="utf-8")


def test_the_sidebar_focus_ring_reaches_3_to_1_on_its_background_in_both_themes():
    # DOC474.97 (WCAG 1.4.11): a grey oklch(L 0 0) has a relative luminance of about L**3
    css = (UI.parents[1] / "index.css").read_text(encoding="utf-8")

    def grey(block: str, name: str) -> float:
        found = re.search(rf"{name}:\s*oklch\(([\d.]+) 0 0\)", block)
        assert found, name
        return float(found.group(1)) ** 3

    light, dark = css[css.index(":root {"):css.index(".dark {")], css[css.index(".dark {"):css.index("@layer base")]
    for theme in (light, dark):
        ring, bg = grey(theme, "--sidebar-ring"), grey(theme, "--sidebar")
        hi, lo = max(ring, bg), min(ring, bg)
        assert (hi + 0.05) / (lo + 0.05) >= 3, theme[:6]


def test_the_outline_of_an_input_reaches_3_to_1_in_both_themes_and_the_tint_tokens_are_untouched():
    # DOC534.141 (WCAG 1.4.11): --input (0.922) gave about 1.3:1 on white, white at 15% about 1.5:1 in the dark theme
    css = (UI.parents[1] / "index.css").read_text(encoding="utf-8")
    light, dark = css[css.index(":root {"):css.index(".dark {")], css[css.index(".dark {"):css.index("@layer base")]
    field = float(re.search(r"--field:\s*oklch\(([\d.]+) 0 0\)", light).group(1))
    assert (1 + 0.05) / (field ** 3 + 0.05) >= 3                                         # on the white page and cards
    alpha = int(re.search(r"--field:\s*oklch\(1 0 0 / (\d+)%\)", dark).group(1)) / 100
    for background in (0.145, 0.205):                                                    # the page and the cards of the dark theme
        blended = background * (1 - alpha) + alpha                                       # a white outline over it
        assert (blended ** 3 + 0.05) / (background ** 3 + 0.05) >= 3, background
    assert "--color-field: var(--field)" in css
    input_source = (UI / "input.tsx").read_text(encoding="utf-8")
    assert "border border-field" in input_source and "border border-input" not in input_source
    assert "disabled:bg-input/50" in input_source and "--input: oklch(0.922 0 0)" in light and "--input: oklch(1 0 0 / 15%)" in dark   # tints stay


def test_the_notice_live_regions_are_never_hidden_while_empty():
    # DOC474.108: `empty:hidden` is display:none on the empty region, which removes it from the accessibility tree: it comes
    # back together with its text, the very case the "always in the page" comment is there to avoid
    bits = (UI.parents[0] / "Bits.tsx").read_text(encoding="utf-8")
    notice = bits[bits.index("export function Notice"):bits.index("const STATUS_CLASS")]
    assert 'role="status"' in notice and 'role="alert"' in notice and "empty:hidden" not in notice


def test_a_ticked_item_that_stops_being_approvable_leaves_the_selection():
    # DOC474.145: an item that turned into a duplicate or an error after a reload stayed ticked and was sent to the batch
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text(encoding="utf-8")
    assert queue.index("const approvable = ") < queue.index("setTicked((t) => new Set(list")   # defined before load() uses it
    assert "list.filter((i) => t.has(i.id) && approvable(i))" in queue          # on every reload (also the polled ones go through load)
    assert "const ticks = items.filter((i) => ticked.has(i.id) && approvable(i))" in queue   # and again where the count and the call are made


def test_the_csrf_cookie_value_is_everything_after_the_name_not_the_text_before_the_next_equals_sign():
    # DOC474.165: split('=')[1] cut a value that contains "=" (base64-like) at its first "="
    api = (UI.parents[1] / "api.ts").read_text(encoding="utf-8")
    csrf = api[api.index("function csrf()"):api.index("/** Every readable string")]
    assert ".split('=')[1]" not in csrf and "c.slice('csrftoken='.length)" in csrf


def test_an_older_dashboard_answer_never_overwrites_a_newer_one():
    # DOC474.176: the visibility refresh can overlap the scheduled one; a late OLD answer replaced the newest counters
    page = (UI.parents[1] / "pages" / "Dashboard.tsx").read_text(encoding="utf-8")
    body = page[page.index("const fetchNow"):page.index("const load = ")]
    assert "const mine = ++latest.current" in body                              # every request takes a number first
    assert body.index("await api.dashboard()") < body.index("if (mine !== latest.current) return")   # a stale answer is dropped
    assert body.index("if (mine !== latest.current) return") < body.index("setD(fresh)")
    assert "const latest = useRef(0)" in page


def test_the_scan_refresh_reselects_when_the_selected_item_left_the_list_and_forgets_its_tick():
    # DOC474.33: only "nothing selected" triggered a reselection; an item filed elsewhere left an empty panel next to a full list
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text(encoding="utf-8")
    tick = queue[queue.index("const tick = async"):queue.index("timer = setTimeout(tick, 3000)\n    return")]   # the end of the tick, not a retry in it
    assert "selRef.current === null || !list.some((i) => i.id === selRef.current)" in tick
    assert "!dirtyRef.current" in tick                                           # never over a form the user has edited
    assert "setTicked((t) => new Set(list.filter((i) => t.has(i.id) && approvable(i)).map((i) => i.id)))" in tick
    assert "dirtyRef.current = !!dirty" in queue


def test_an_empty_or_out_of_range_confidence_threshold_selects_nothing():
    # DOC474.34: Number('') is 0, so an emptied field ticked every approvable item, whatever its confidence
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text(encoding="utf-8")
    assert "const minValid = minConf.trim() !== '' && Number.isFinite(Number(minConf)) && Number(minConf) >= 0 && Number(minConf) <= 100" in queue
    assert "const selectFrom = () => minValid && tick(" in queue
    assert "disabled={busy || !items.length || !minValid} onClick={selectFrom}" in queue


def test_the_confidence_threshold_compares_the_percentage_the_screen_shows_not_a_float_below_it():
    # DOC534.72: 0.29 * 100 is 28.999999999999996, so a document shown as "29 %" was not ticked by a threshold of 29
    assert 0.29 * 100 < 29 <= round(0.29 * 100)                                      # the arithmetic the screen has to absorb
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text(encoding="utf-8")
    assert "Math.round(i.confidence * 100) >= Number(minConf)" in queue and "i.confidence * 100 >=" not in queue


def test_each_api_type_has_its_own_doc_comment_directly_above_it():
    # DOC474.58: two JSDoc blocks in a row, the first one (about Group) sat above Batch's comment and documented nothing
    api = (UI.parents[1] / "api.ts").read_text(encoding="utf-8")
    assert not re.search(r"\*/\n/\*\*", api), "two doc comments follow each other"
    assert re.search(r"/\*\* The four disjoint categories[^\n]*\*/\nexport type Group =", api)
    assert re.search(r"/\*\* The answer of a bulk approval[^\n]*\*/\nexport type Batch =", api)


def test_the_search_runs_on_submit_only_and_never_while_a_search_is_in_flight():
    # DOC474.60 feared stale answers from searches fired while typing; there is one request at a time, started by a submit
    page = (UI.parents[1] / "pages" / "Search.tsx").read_text(encoding="utf-8")
    submit = page[page.index("const submit"):page.index("return (", page.index("const submit"))]
    assert "if (busy || !query.trim()) return" in submit and submit.index("if (busy") < submit.index("api.search")
    assert page.count("api.search(") == 1                                              # the only caller: submit
    assert "onChange={(e) => setQuery(e.target.value)}" in page                       # typing only edits the text...
    assert "onSubmit={submit}" in page and "disabled={busy || !query.trim()}" in page      # ...and the button is off while busy


def test_the_total_count_header_is_a_whole_number_or_null_never_nan_or_zero_from_an_empty_string():
    # DOC474.61: Number('') is 0 and Number('abc') is NaN; `total ?? data.length` replaces neither
    api = (UI.parents[1] / "api.ts").read_text(encoding="utf-8")
    start = api.index("const total = r.headers.get('X-Total-Count')")
    body = api[start:api.index("\n}", start)]                                       # up to the end of request(), return included
    assert "/^\\d+$/.test(total)" in body                                           # digits only, so '', ' ', 'abc', '-1', '1.5' are out
    assert "Number(total)" in body and "null" in body


def test_the_dashboard_comment_does_not_promise_that_two_requests_are_never_in_flight_together():
    # DOC474.77: the visibility refresh can overlap the scheduled one; what is promised is that a stale answer is ignored
    page = (UI.parents[1] / "pages" / "Dashboard.tsx").read_text(encoding="utf-8")
    assert "never in flight together" not in page
    assert "const mine = ++latest.current" in page and "if (mine !== latest.current) return" in page    # the real guarantee


def test_a_network_failure_reaches_the_screens_as_a_translated_api_error_never_as_a_raw_typeerror():
    # DOC474.78 feared "TypeError: Failed to fetch" in English on the dashboard: request() converts the fetch rejection first
    api = (UI.parents[1] / "api.ts").read_text(encoding="utf-8")
    body = api[api.index("async function request"):api.index("const data = await r.json()")]
    assert "r = await fetch(" in body and "catch (e) {" in body                                # the rejection is caught here...
    assert "throw new ApiError('Network error: the server cannot be reached.')" in body        # ...and becomes an ApiError
    assert body.index("r = await fetch(") < body.index("catch (e) {") < body.index("throw new ApiError('Network error")


def test_saving_the_settings_goes_through_request_so_a_lost_network_is_a_translated_api_error():
    # DOC534.92: saveSettings called fetch itself: a server that could not be reached gave "Unexpected error." (a raw TypeError)
    api = (UI.parents[1] / "api.ts").read_text(encoding="utf-8")
    save = api[api.index("saveSettings: async"):api.index("folders: (path")]
    assert "fetch(" not in save and "await call<FolderSettings>('POST', '/api/settings', values)" in save
    assert "throw new ApiError(errorMessage(data, r.status), r.status, data)" in api        # the refusal's body reaches the caller
    assert "e.status === 400" in save and "throw new SettingsRefused(errors)" in save and save.rstrip().endswith("},")


def test_a_request_the_server_never_answers_ends_with_a_translated_timeout_and_the_slow_ones_wait_longer():
    # DOC534.95: fetch had no timeout: a server that accepted the connection and said nothing left the screen loading for ever
    setup = """
      globalThis.document = { cookie: '' }
      globalThis.seen = []
      globalThis.fetch = (url, init) => new Promise((resolve, reject) => {
        seen.push({ url, aborts: !!init.signal })
        init.signal.addEventListener('abort', () => reject(init.signal.reason))    // as the real fetch does when the signal fires
      })
      const real = AbortSignal.timeout.bind(AbortSignal)
      globalThis.waited = []
      AbortSignal.timeout = (ms) => { waited.push(ms); return real(5) }               // the clock is short in the test, the duration is recorded
      globalThis.keepAlive = setInterval(() => {}, 20)                                  // node's timeout timer does not keep the process alive
    """
    got = _node_route("""(async () => {
      const out = {}
      try { await m.api.dashboard() } catch (e) { out.message = e.message; out.type = e.constructor.name }
      try { await m.api.approveAuto() } catch (e) { out.slow = e.message }
      try { await m.api.libraryPlan('a.pdf') } catch (e) { out.plan = e.message }
      out.waited = waited
      clearInterval(keepAlive)
      return out
    })()""", module="api", setup=setup)
    assert got["type"] == "ApiError" and got["message"] == "Request timed out: the server did not answer."
    assert got["waited"] == [60_000, 900_000, 900_000]                                        # a minute, and 15 for approvals and OCR
    assert got["slow"] == got["plan"] == got["message"]
    assert "'Request timed out: the server did not answer.': " in (UI.parents[1] / "i18n.tsx").read_text(encoding="utf-8")   # and it is translated


def test_the_language_asked_of_the_changelog_is_encoded_like_every_other_query_value():
    # DOC534.94: `?lang=${lang}` was the one query built by hand: a value with & or # would have corrupted the request
    setup = """
      globalThis.document = { cookie: '' }
      globalThis.asked = []
      globalThis.fetch = async (url) => { asked.push(url); return { ok: true, status: 200, json: async () => [], headers: { get: () => null } } }
    """
    got = _node_route("""(async () => { await m.api.changelog('fr'); await m.api.changelog('fr&x=1#top'); return asked })()""",
                      module="api", setup=setup)
    assert got == ["/api/changelog?lang=fr", "/api/changelog?lang=fr%26x%3D1%23top"]               # one parameter, whatever the value


def test_saving_the_settings_behaves_the_same_whatever_goes_wrong_with_the_answer():
    # DOC534.93 (and .92), run for real: an HTML page with status 200 (captive portal), a lost network and a refusal
    setup = """
      globalThis.document = { cookie: '' }
      let mode = ''
      globalThis.fetch = async () => {
        if (mode === 'down') throw new TypeError('Failed to fetch')
        if (mode === 'html') return { ok: true, status: 200, json: async () => { throw new SyntaxError('<html>') }, headers: { get: () => null } }
        return { ok: false, status: 400, json: async () => ({ detail: 'x', errors: { inbox: 'does not exist' } }), headers: { get: () => null } }
      }
      globalThis.setMode = (m) => { mode = m }
    """
    got = _node_route("""(async () => {
      const outcome = async (mode) => { setMode(mode); try { await m.api.saveSettings({}); return 'saved' } catch (e) { return [e.constructor.name, e.message, e.errors ?? null] } }
      return { down: await outcome('down'), html: await outcome('html'), refused: await outcome('refused') }
    })()""", module="api", setup=setup)
    assert got["down"][:2] == ["ApiError", "Network error: the server cannot be reached."]          # not a raw TypeError
    assert got["html"][0] == "ApiError" and "unexpected response" in got["html"][1]                  # not `undefined` typed as the settings
    assert got["refused"] == ["SettingsRefused", "does not exist", {"inbox": "does not exist"}]      # the refusal still names the setting


def test_the_dashboard_comment_says_the_today_tile_opens_the_unfiltered_history():
    # DOC474.79: "each tile opens exactly what it counts" was not true of the "Filed today" tile
    page = (UI.parents[1] / "pages" / "Dashboard.tsx").read_text(encoding="utf-8")
    assert "each tile opens exactly what it counts" not in page
    assert "newest first" in page and "not filtered by date" in page


def test_the_route_groups_cannot_drift_from_the_group_type_without_the_compiler_saying_so():
    # DOC534.174: GROUPS duplicated the Group type of api.ts; a new group was rejected by parseHash in silence
    import re
    src = UI.parents[1]
    route = (src / "route.ts").read_text(encoding="utf-8")
    assert "const GROUPS: Group[]" not in route
    assert "satisfies Record<Group, true>" in route and "Object.keys(GROUP_KEYS) as Group[]" in route
    declared = re.search(r"export type Group = ([^\n]+)", (src / "api.ts").read_text(encoding="utf-8")).group(1)
    assert sorted(re.findall(r"'(\w+)'", declared)) == sorted(re.findall(r"(\w+): true", route))           # and they agree today


def test_the_notes_inline_markup_only_styles_the_matches_of_the_split():
    # DOC534.152: "**unclosed" is no match, yet startsWith('**') made it bold and cut two characters off each end
    page = (UI.parents[1] / "pages" / "Notes.tsx").read_text(encoding="utf-8")
    assert "i % 2 === 1 && part.startsWith('**')" in page and "i % 2 === 1 && part.startsWith('`')" in page
    assert "\n        part.startsWith(" not in page


def test_the_notes_keys_carry_the_position_so_a_repeated_bullet_or_title_does_not_clash():
    # DOC534.153: two equal bullets in a section (or two sections with one title) gave React duplicate keys
    page = (UI.parents[1] / "pages" / "Notes.tsx").read_text(encoding="utf-8")
    assert "key={item}" not in page and "key={s.title}" not in page and "key={r.version}" not in page
    assert "key={`${ii}-${item}`}" in page and "key={`${si}-${s.title}`}" in page and "key={`${index}-${r.version}`}" in page


def test_the_card_title_comment_does_not_bless_a_card_inside_a_button():
    # DOC534.151: it said a card inside a <button> is fine if the title is no heading, but the card itself is made of <div>s
    card = (UI / "card.tsx").read_text(encoding="utf-8")
    assert "a card inside a <button>" not in card
    assert "never goes inside a <button>" in card


def test_a_long_source_path_wraps_in_its_card_and_leaves_the_count_in_view():
    # DOC534.257: an absolute path has no space to break at; it ran out of the card and pushed the number of PDFs out of sight
    page = (UI.parents[1] / "pages" / "Dashboard.tsx").read_text(encoding="utf-8")
    row = page[page.index("d.sources.map"):page.index("</CardContent>", page.index("d.sources.map"))]
    assert 'className="flex justify-between gap-3 border-b py-2 last:border-0"' in row
    assert '<span className="min-w-0">' in row and 'className="ml-2 break-all text-slate-500">{s.path}' in row
    assert '<span className="shrink-0 font-medium">{t(\'dash.pdfCount\'' in row


def test_a_dashboard_tile_is_a_button_made_of_inline_elements_only():
    # DOC474.80: Card, CardHeader and CardContent render <div>s; a <button> may only hold phrasing content
    page = (UI.parents[1] / "pages" / "Dashboard.tsx").read_text(encoding="utf-8")
    start = page.index("<button key={label}")
    tile = page[start:page.index("</button>", start)]
    assert "<Card" not in tile and "<div" not in tile and "<h" not in tile
    assert tile.count("<span") >= 3 and "{t(label)}" in tile and "{n}" in tile


def test_an_operation_kind_the_front_end_does_not_know_is_shown_as_its_own_name_not_as_a_raw_key():
    # DOC474.81: t(`op.${kind}` as AskKey) printed "op.xxx" for a kind added by the server, and the cast hid it from the compiler
    src = UI.parents[1]
    ops = (src / "ops.ts").read_text(encoding="utf-8")
    assert "Record<string, AskKey>" in ops and "'op.move'" in ops and "'op.quarantine'" in ops
    assert "Object.hasOwn(OP_KEYS, kind) ? t(OP_KEYS[kind]) : kind" in ops              # unknown kind: its own name (DOC474.110)
    for page in ("Dashboard.tsx", "History.tsx"):
        text = (src / "pages" / page).read_text(encoding="utf-8")
        assert "opLabel(t, o.kind)" in text and "`op.${o.kind}`" not in text, page      # the unchecked cast is gone
    server_kinds = set(re.findall(r'add_op\(\w+, "(\w+)"', (UI.parents[3] / "backend" / "docflow" / "pipeline.py").read_text(encoding="utf-8")))
    assert server_kinds and all(f"'op.{k}'" in ops for k in server_kinds), server_kinds      # every kind the server writes


def test_each_forget_button_of_an_alias_pattern_has_its_own_accessible_name():
    # DOC474.85: a company with several patterns gave several buttons all named "Forget the rule of <company>"
    root = UI.parents[1]
    rules = (root / "pages" / "Rules.tsx").read_text(encoding="utf-8")
    assert "pattern ? t('rules.forgetPatternLabel', { company, pattern }) : t('rules.forgetLabel', { company })" in rules
    i18n = (root / "i18n.tsx").read_text(encoding="utf-8")
    en, fr = i18n[i18n.index("const en"):i18n.index("const fr")], i18n[i18n.index("const fr"):]
    for block in (en, fr):
        assert "'rules.forgetPatternLabel'" in block and "{pattern}" in block.split("'rules.forgetPatternLabel'")[1].split("\n")[0]


def test_each_comment_of_the_rules_loader_sits_on_the_line_it_describes():
    # DOC534.259: the comment about the value load() resolves with stood above the haveRules ref, which has a comment of its own
    rules = (UI.parents[1] / "pages" / "Rules.tsx").read_text(encoding="utf-8").splitlines()
    have = next(i for i, line in enumerate(rules) if "const haveRules = useRef(false)" in line)
    load = next(i for i, line in enumerate(rules) if "const load = useCallback(" in line)
    assert "the rules were read at least once" in rules[have]                                    # its own comment, on its own line
    assert "resolves true when the rules were read" in rules[load - 1]                           # the load comment, right above load
    assert "true when the rules were read" not in rules[have - 1]


def test_enter_in_the_destination_field_saves_like_the_button_and_nothing_else_submits():
    # DOC534.258: the destination had to be saved with a click on the button
    rules = (UI.parents[1] / "pages" / "Rules.tsx").read_text(encoding="utf-8")
    row = rules[rules.index("const unchanged"):rules.index("{forgetButton('route', r.company)}")]
    assert "<form " in row and "onSubmit={(e) => { e.preventDefault(); if (!busy && !unchanged) void saveRoute(r.company, value.trim()) }}" in row
    assert '<Button type="submit" size="sm" disabled={busy || unchanged}>' in row                    # the one submit button; disabled = no Enter save
    assert "onClick={() => saveRoute" not in rules                                                   # one way to save, not two
    forget = rules[rules.index("const forgetButton"):rules.index("const section")]
    assert '<Button type="button"' in forget                                                         # in a form, Forget must not submit it


def test_a_saved_destination_stays_on_screen_until_the_rules_are_reloaded():
    # DOC474.86: the draft was dropped right after the save, so the field showed the OLD destination until load() ended (and for
    # good if the reload failed)
    rules = (UI.parents[1] / "pages" / "Rules.tsx").read_text(encoding="utf-8")
    save = rules[rules.index("const saveRoute"):rules.index("const filed")]
    # DOC534.226: saveRoute hands the call to act(), which awaits it; the awaiting is read where it happens, in act
    assert "() => api.setRoute(company, destination)" in save
    assert "dropDraft(company)" in save and save.index("api.setRoute") < save.index("dropDraft")   # (dropDraft = setDrafts without that company)
    assert "const loaded = await load()" in rules and "if (loaded) after?.()" in rules          # the draft goes only after a good reload
    act = rules[rules.index("const act"):rules.index("const forget")]
    assert act.index("await action()") < act.index("await load()") < act.index("after?.()")        # saved, THEN reloaded, THEN the draft goes
    assert "setDrafts" not in act.split("await load()")[0]                                         # and never before it


def test_a_route_destination_is_trimmed_before_it_is_compared_and_sent():
    # DOC474.87: only the "empty" test trimmed; " Bills/Hydro " was sent as typed, and a change of spaces alone counted as an edit
    rules = (UI.parents[1] / "pages" / "Rules.tsx").read_text(encoding="utf-8")
    # (DOC534.258: the same two things, now behind a form: `unchanged` compares the trimmed value, and the submit sends the trimmed value)
    assert "const unchanged = value.trim() === r.destination || !value.trim()" in rules
    assert "void saveRoute(r.company, value.trim())" in rules and "disabled={busy || unchanged}" in rules


def test_a_failed_reload_after_a_change_keeps_the_rules_and_the_success_message_on_screen():
    # DOC474.88: loadError replaces the whole page; a passing error after a successful save hid the list and the "saved" message
    rules = (UI.parents[1] / "pages" / "Rules.tsx").read_text(encoding="utf-8")
    load = rules[rules.index("const load = "):rules.index("useEffect(() => { load() }")]
    assert "haveRules.current" in load and "setReloadError(" in load and "setLoadError(" in load      # two cases, told apart
    failure = load[load.index(".catch("):]
    assert failure.index("haveRules.current") < failure.index("setReloadError(") < failure.index("setLoadError(")   # kept list first
    assert "const haveRules = useRef(false)" in rules and "haveRules.current = true" in load
    # both shown, whether the action succeeded or FAILED (DOC534.32: a failed action's text was hidden behind the old reload error)
    assert "reloadError ? { ok: false, text: `${note ? `${note.text} ` : ''}${msg(reloadError)}` } : note" in rules
    assert "note?.ok" not in rules


def test_a_truncated_label_of_the_accuracy_screen_can_still_be_read_in_full():
    # DOC474.106: a long company name ended in an ellipsis with no tooltip: two companies starting alike could not be told apart
    accuracy = (UI.parents[1] / "components" / "Accuracy.tsx").read_text(encoding="utf-8")
    assert '<span className="min-w-0 truncate" title={label}>{label}</span>' in accuracy


def test_the_accuracy_screen_announces_that_it_is_loading_and_that_the_figures_arrived():
    # DOC474.107: after "Retry" the content changed with no announcement for a screen reader
    root = UI.parents[1]
    accuracy, i18n = (root / "components" / "Accuracy.tsx").read_text(encoding="utf-8"), (root / "i18n.tsx").read_text(encoding="utf-8")
    assert '<p role="status" className="sr-only">' in accuracy                       # always in the page, empty or not
    status = accuracy[accuracy.index('<p role="status" className="sr-only">'):]
    status = status[:status.index("</p>")]
    assert "t('common.loading')" in status and "t('acc.loaded')" in status
    en, fr = i18n[i18n.index("const en"):i18n.index("const fr")], i18n[i18n.index("const fr"):]
    assert "'acc.loaded'" in en and "'acc.loaded'" in fr


def test_the_same_message_shown_twice_in_a_row_is_a_new_element_so_it_is_announced_again():
    # DOC474.109: React leaves the DOM alone when the text is identical, so a screen reader heard nothing the second time
    bits = (UI.parents[1] / "components" / "Bits.tsx").read_text(encoding="utf-8")
    notice = bits[bits.index("export function Notice"):bits.index("const STATUS_CLASS")]
    assert "const shown = useRef(0)" in notice and "if (note !== last.current)" in notice and "shown.current += 1" in notice
    assert notice.count("key={shown.current}") == 2                                          # the success and the failure paragraph


def test_a_note_built_from_other_state_keeps_its_identity_between_renders():
    # Notice announces a "new" note when the object changes (DOC474.109): one rebuilt at every render would be re-announced each time
    pages = UI.parents[1] / "pages"
    history, rules = (pages / "History.tsx").read_text(encoding="utf-8"), (pages / "Rules.tsx").read_text(encoding="utf-8")
    assert "const shownNote = useMemo(" in history and "[note, loadError, msg, t])" in history
    assert "<Notice note={shownNote} />" in history and "<Notice note={shownNote} />" in rules
    assert "const shownNote = useMemo(" in rules and "[reloadError, note, msg]" in rules


def test_an_unknown_value_named_like_an_object_property_is_not_taken_for_a_known_one():
    # DOC474.110: 'constructor' in {...} is true (inherited from Object): a badge got a function as its class, a label a function
    src = UI.parents[1]
    bits, ops = (src / "components" / "Bits.tsx").read_text(encoding="utf-8"), (src / "ops.ts").read_text(encoding="utf-8")
    assert "const known = Object.hasOwn(STATUS_CLASS, status)" in bits
    assert "known ? STATUS_CLASS[status] : STATUS_CLASS.manual" in bits and "?? STATUS_CLASS.manual" not in bits
    assert "Object.hasOwn(OP_KEYS, kind) ? t(OP_KEYS[kind]) : kind" in ops and "kind in OP_KEYS" not in ops


def test_a_confidence_level_is_given_by_a_symbol_and_a_word_not_only_by_its_colour():
    # DOC474.111: green / amber / red alone leave out colour-blind readers and screen readers
    root = UI.parents[1]
    bits, i18n = (root / "components" / "Bits.tsx").read_text(encoding="utf-8"), (root / "i18n.tsx").read_text(encoding="utf-8")
    conf = bits[bits.index("export function Confidence"):]
    assert "const level = (v: number | undefined)" in conf and "'conf.high'" in conf and "'conf.medium'" in conf and "'conf.low'" in conf
    assert conf.count('<span aria-hidden="true">') >= 1 and conf.count('<span className="sr-only">') >= 1       # a symbol and a hidden word
    assert "shown(item.confidence)" in conf and "shown(item.conf[k])" in conf                                   # global score and each field
    assert "percent(item.confidence)" not in conf and "percent(item.conf[k])" not in conf                       # never the bare number
    en, fr = i18n[i18n.index("const en"):i18n.index("const fr")], i18n[i18n.index("const fr"):]
    for key in ("conf.high", "conf.medium", "conf.low"):
        assert f"'{key}'" in en and f"'{key}'" in fr, key


def test_no_unused_chart_colour_tokens_are_left_in_the_stylesheet():
    # DOC474.98: five grey chart tokens, identical in both themes and at 1.4:1 contrast, that no component uses. Removed rather than
    # tuned: if a chart is ever added it needs a palette made for it. (The test also checks that nothing refers to them.)
    src = UI.parents[1]
    css = (src / "index.css").read_text(encoding="utf-8")
    assert "chart" not in css
    used = [p.name for p in src.rglob("*.ts*") if re.search(r"(?:bg|text|fill|stroke|border|ring)-chart-\d|var\(--chart", p.read_text(encoding="utf-8"))]
    assert used == [], used


def test_muted_text_reaches_4_5_to_1_on_every_surface_it_is_drawn_on_in_both_themes():
    # DOC474.99 (WCAG 1.4.3, normal text): oklch(0.556) on oklch(0.97) is 4.3:1. A grey oklch(L 0 0) has a luminance of about L**3.
    css = (UI.parents[1] / "index.css").read_text(encoding="utf-8")

    def grey(block: str, name: str) -> float:
        found = re.search(rf"\n\s+{name}:\s*oklch\(([\d.]+) 0 0\)", block)
        assert found, name
        return float(found.group(1)) ** 3

    light, dark = css[css.index(":root {"):css.index(".dark {")], css[css.index(".dark {"):css.index("@layer base")]
    for theme in (light, dark):
        text = grey(theme, "--muted-foreground")
        for surface in ("--background", "--muted", "--accent", "--card"):
            other = grey(theme, surface)
            hi, lo = max(text, other), min(text, other)
            assert (hi + 0.05) / (lo + 0.05) >= 4.5, (theme[:6], surface, (hi + 0.05) / (lo + 0.05))


def test_a_failed_reload_after_an_undo_is_shown_with_the_result_of_the_undo():
    # DOC474.117: the "restored" message hid the reload error; the list stayed stale with no sign that it was
    history = (UI.parents[1] / "pages" / "History.tsx").read_text(encoding="utf-8")
    shown = history[history.index("const shownNote"):history.index("// one undo at a time")]
    # DOC534.41: the text of the undo is kept whether it succeeded or FAILED
    assert "return loadError ? { ok: false, text: `${said ? `${said.text} ` : ''}${msg(loadError)}` } : said" in shown
    assert "note?.ok" not in shown
    assert "[note, loadError, msg, t]" in shown                                               # (the note keeps its identity)


def test_the_retry_button_of_the_accuracy_card_does_not_vanish_under_the_keyboard_focus():
    # DOC534.148: the click cleared the error, the block and its button went, and the focus fell back to <body>
    page = (BITS.parent / "Accuracy.tsx").read_text(encoding="utf-8")
    retry = page[page.index("const retry = "):page.index("const GOOD")] if "const GOOD" in page else page
    assert "onClick={retry}" in page and "onClick={() => { setError(''); void load() }}" not in page          # the click clears nothing
    assert "if (retrying) return" in retry and "aria-disabled={retrying}" in page                      # and cannot be repeated meanwhile
    assert "document.getElementById('accuracy-title')?.focus()" in retry and "if (ok)" in retry         # focus to the card title once it worked
    assert 'id="accuracy-title" tabIndex={-1}' in page                                                  # which can take focus
    assert "setError(''); return true" in page and "setError(errorText(e)); return false" in page      # load() says whether it worked


def test_a_failed_load_of_the_history_can_be_tried_again_from_the_page():
    # DOC534.144: after a failed first load there was an error and an empty table, and only reloading the whole page tried again
    page = (UI.parents[1] / "pages" / "History.tsx").read_text(encoding="utf-8")
    assert "{loadError && <Button variant=\"outline\" size=\"sm\" onClick={() => void load()}>{t('common.retry')}</Button>}" in page
    assert page.index("<Notice note={shownNote} />") < page.index("onClick={() => void load()}") < page.index("<table")   # next to the message
    assert "setLoadError('')" in page[page.index("const load = "):page.index("useEffect(() => { load() }")]       # and a good load clears it


def test_the_loading_region_of_the_history_is_in_the_page_before_its_text():
    # DOC534.143: <p role="status"> appeared together with "Loading...": a live region added with its content is often not announced
    page = (UI.parents[1] / "pages" / "History.tsx").read_text(encoding="utf-8")
    assert """<div role="status">{ops === null && !loadError && <p className="text-slate-500">{t('common.loading')}</p>}</div>""" in page
    assert """{ops === null && !loadError && <p role="status\"""" not in page            # the region itself is no longer the conditional element


def test_the_result_of_an_undo_is_worded_when_shown_so_it_follows_a_change_of_language():
    # DOC534.142: the sentence was built in the language of the moment and kept: after a switch it stayed in the old one
    history = (UI.parents[1] / "pages" / "History.tsx").read_text(encoding="utf-8")
    undo = history[history.index("const undo = async"):history.index("return (\n    <div")]
    assert "setNote({ ok: true, detail: r.restored })" in undo and "setNote({ ok: false, detail: errorText(e) })" in undo
    assert "t('hist.restored'" not in undo and "msg(" not in undo                             # nothing worded where the note is made
    shown = history[history.index("const shownNote"):history.index("// one undo at a time")]
    assert "t('hist.restored', { path: note.detail })" in shown and "msg(note.detail)" in shown   # worded where it is shown
    assert "useState<{ ok: boolean; detail: string } | null>(null)" in history


def test_keyboard_focus_stays_in_the_history_row_during_and_after_an_undo():
    # DOC474.118: the pressed button became disabled, then was replaced by the "undone" label: focus fell back to <body>
    history = (UI.parents[1] / "pages" / "History.tsx").read_text(encoding="utf-8")
    assert 'aria-disabled={undoing !== null}' in history and not re.search(r"(?<!aria-)disabled=\{undoing", history)   # still focusable
    assert "tabIndex={-1}" in history and "id={`op-${o.id}`}" in history                                       # the row can take focus
    undo = history[history.index("const undo = "):history.index("return (", history.index("const undo = "))]
    assert undo.index("await load()") < undo.index("document.getElementById(`op-${id}`)?.focus()")             # after the reload
    # DOC534.145: only after a SUCCESS (the button is gone then); after a failure the button is still there and keeps the focus
    assert "let undone = false" in undo and "undone = true" in undo and "if (undone) requestAnimationFrame(" in undo
    assert undo.index("undone = true") < undo.index("catch (e)") and undo.rindex("undone") > undo.index("setUndoing(null)")


def test_the_undone_label_is_an_inline_block_so_the_struck_through_row_does_not_strike_it():
    # DOC474.120 feared the "Undone" label was itself struck through. A text decoration set on an ancestor is not propagated to
    # inline-block descendants (CSS Text, "atomic inline-level"): the label must stay an inline-block for that to hold
    history = (UI.parents[1] / "pages" / "History.tsx").read_text(encoding="utf-8")
    assert "o.undone ? 'text-slate-500 line-through' : ''" in history                      # the row IS struck through
    assert re.search(r'<span className="inline-block [^"]*">\{t\(\'hist\.undone\'\)\}</span>', history)   # and the label escapes it


def test_a_failed_search_does_not_leave_the_results_of_the_previous_one_on_screen():
    # DOC474.121: the error appeared above the OLD list, which looked like the answer to the new query
    page = (UI.parents[1] / "pages" / "Search.tsx").read_text(encoding="utf-8")
    submit = page[page.index("const submit"):page.index("return (", page.index("const submit"))]
    assert "setHits(null)" in submit.split("try {")[0], "the old results must go before the new request starts"


def test_an_error_that_is_not_an_api_error_is_logged_and_shown_as_a_generic_translated_message():
    # DOC474.146 / .175 (and .78 / .130 for the network case): String(e) put a raw technical text in front of the user
    src = UI.parents[1]
    api = (src / "api.ts").read_text(encoding="utf-8")
    helper = api[api.index("export function errorText"):]
    helper = helper[:helper.index("\n}\n")]
    assert "e instanceof ApiError" in helper and "console.error(e)" in helper and "'Unexpected error.'" in helper
    offenders = [p.name for p in src.rglob("*.ts*") if p.name != "api.ts" and re.search(r"String\((e|x)\)", p.read_text(encoding="utf-8"))]
    assert offenders == [], offenders                                          # every screen goes through the helper
    for page in ("App.tsx", "components/Accuracy.tsx", "pages/Rules.tsx", "pages/Dashboard.tsx", "pages/Search.tsx",
                 "pages/History.tsx", "pages/Queue.tsx"):
        assert "errorText(" in (src / page).read_text(encoding="utf-8"), page
    i18n = (src / "i18n.tsx").read_text(encoding="utf-8")
    from conftest import fr_messages_table
    assert "'Unexpected error.':" in fr_messages_table(i18n)                      # and its French text exists


def test_the_contrast_figures_quoted_in_the_focus_ring_comment_are_the_computed_ones():
    # DOC474.185 doubted the "4.7:1" of the --ring comment. A grey oklch(L 0 0) has a relative luminance of L**3, so on white
    # the contrast is 1.05 / (L**3 + 0.05): 0.556 -> 4.73, 0.708 -> 2.59. The comment must say what the numbers say.
    css = (UI.parents[1] / "index.css").read_text(encoding="utf-8")
    line = next(row for row in css.splitlines() if row.strip().startswith("--ring:") and "on white" in row)
    ring = float(re.search(r"oklch\(([\d.]+) 0 0\)", line).group(1))
    said = float(re.search(r"(\d+\.\d):1 on white", line).group(1))
    said_before = float(re.search(r"([\d.]+) gave (\d+\.\d):1", line).group(2))
    old = float(re.search(r"([\d.]+) gave", line).group(1))
    assert abs(1.05 / (ring ** 3 + 0.05) - said) < 0.06, (said, 1.05 / (ring ** 3 + 0.05))
    assert abs(1.05 / (old ** 3 + 0.05) - said_before) < 0.06, (said_before, 1.05 / (old ** 3 + 0.05))


def test_the_history_table_names_itself_and_ties_each_header_to_its_column():
    # DOC474.194: no scope on the headers, no caption: a screen reader moving cell by cell could not tell the columns apart
    root = UI.parents[1]
    history, i18n = (root / "pages" / "History.tsx").read_text(encoding="utf-8"), (root / "i18n.tsx").read_text(encoding="utf-8")
    head = history[history.index("<thead>"):history.index("</thead>")]
    assert len(re.findall(r"<th[\s>]", head)) == 6 and head.count('<th scope="col"') == 6            # all six headers carry the scope
    assert '<caption className="sr-only">{t(\'hist.caption\')}</caption>' in history
    en, fr = i18n[i18n.index("const en"):i18n.index("const fr")], i18n[i18n.index("const fr"):]
    assert "'hist.caption'" in en and "'hist.caption'" in fr


def test_a_long_badge_label_ends_in_an_ellipsis_and_can_be_read_in_full():
    # DOC474.203 feared a silently cut badge. The only Badge is the status badge: its label sits in a `truncate` span (hidden
    # overflow + ellipsis) and the badge carries the whole text as its title
    src = UI.parents[1]
    users = [p.name for p in src.rglob("*.tsx") if "<Badge" in p.read_text(encoding="utf-8") and p.name != "badge.tsx"]
    assert users == ["Bits.tsx"], users
    bits = (src / "components" / "Bits.tsx").read_text(encoding="utf-8")
    assert 'title={label}>' in bits and '<span className="truncate">{label}</span>' in bits


def test_changing_the_filter_keeps_the_open_document_and_what_was_typed_in_it():
    # DOC474.214: a new group reloads the list; the open document and its unsaved form survive when it is still listed
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text(encoding="utf-8")
    assert "async (keep?: number | null, stay = false)" in queue
    assert "if (stay && dirtyRef.current && next?.id === keep) return" in queue
    assert "load(selRef.current, true)" in queue  # the filter effect asks to stay; a save (load(keep)) still refreshes the form


def test_each_doc_comment_of_api_ts_sits_right_above_the_type_it_describes():
    # DOC474.226 feared the Group comment above Batch: each type has its own comment, directly on top of it
    api = (UI.parents[1] / "api.ts").read_text(encoding="utf-8")
    for text, decl in (("The answer of a bulk approval", "export type Batch"), ("The four disjoint categories", "export type Group")):
        line = next(l for l in api.splitlines() if text in l)
        assert api.splitlines()[api.splitlines().index(line) + 1].startswith(decl), text


def test_the_dashboard_counters_are_announced_when_they_change_not_on_every_refresh():
    # DOC474.236: the tiles refresh by themselves; a screen reader hears the new numbers, but the "updated at" line stays silent
    dash = (UI.parents[1] / "pages" / "Dashboard.tsx").read_text(encoding="utf-8")
    assert """<p role="status" className="sr-only">{tiles.map(([label, n]) => `${t(label)}: ${n}`).join(', ')}</p>""" in dash
    updated = next(l for l in dash.splitlines() if "dash.updated" in l)
    assert "role=" not in updated and "aria-live" not in updated      # a timestamp that changes every 15 s must not be announced


def test_a_failed_background_refresh_of_the_dashboard_says_the_figures_may_be_old():
    # DOC474.237: after a failed quiet refresh the old numbers stayed with no sign but a discreet time
    dash = (UI.parents[1] / "pages" / "Dashboard.tsx").read_text(encoding="utf-8")
    assert "if (quiet && shown.current) setStale(true)" in dash and "setStale(false)" in dash         # set on a failed refresh, cleared on a good one
    assert """{stale && <p role="alert\"""" in dash and "t('dash.stale')" in dash


def test_a_row_of_tabs_wider_than_the_screen_wraps_instead_of_being_cut_off_or_showing_scroll_arrows():
    # DOC474.269: the list is h-8 = 2rem, so it follows the text size; what could still be cut was a row wider than the screen.
    # It now wraps onto a second line: an overflow scroller showed arrows in the desktop window.
    app = (UI.parents[1] / "App.tsx").read_text(encoding="utf-8")
    assert '<TabsList className="h-auto max-w-full flex-wrap group-data-horizontal/tabs:h-auto">' in app
    assert "overflow-x-auto" not in app
    assert "group-data-horizontal/tabs:h-8" in (UI / "tabs.tsx").read_text(encoding="utf-8")   # rem, not px: it grows with the user's text size


def test_french_texts_get_no_break_spaces_before_punctuation_and_inside_guillemets():
    # DOC474.30: a line must not break between « and its word, or leave a lone ":" at the start of the next line
    got = _node_route("""{
      colon: m.frenchSpaces('Total : 5'), guillemets: m.frenchSpaces('Oublier le motif « ACME » de X'),
      marks: m.frenchSpaces('Quoi ? Oui ! Bon ; non'), plain: m.frenchSpaces('Texte sans ponctuation, tout simple.'),
      none: m.frenchSpaces('http://x.org:80/a') }""", module="typography")
    assert got["colon"] == "Total : 5" and got["guillemets"] == "Oublier le motif « ACME » de X"
    assert got["marks"] == "Quoi ? Oui ! Bon ; non" and got["plain"] == "Texte sans ponctuation, tout simple."
    # DOC534.14: the characters themselves, by code (a literal no-break space looks like a plain one and is lost in a reformat)
    nb = chr(0xA0)
    assert got["colon"] == f"Total{nb}: 5" and got["marks"] == f"Quoi{nb}? Oui{nb}! Bon{nb}; non"
    assert got["guillemets"] == f"Oublier le motif {chr(0xAB)}{nb}ACME{nb}{chr(0xBB)} de X"
    assert got["none"] == "http://x.org:80/a"                                # a colon with no space before it is left alone
    i18n = (UI.parents[1] / "i18n.tsx").read_text(encoding="utf-8")
    assert "lang === 'fr' ? frSpaced : en" in i18n and "frMessagesSpaced[text]" in i18n   # the screen reads the spaced copies


def test_the_lists_in_the_messages_use_one_localized_separator_in_both_languages():
    # DOC474.35: failures were joined with " ; ", what was learned with "; ". DOC534.227: and in French the semicolon asks for a
    # no-break space before it, which frenchSpaces never gives to a separator built at run time
    pages = UI.parents[1] / "pages"
    queue, library = (pages / "Queue.tsx").read_text(encoding="utf-8"), (pages / "Library.tsx").read_text(encoding="utf-8")
    for source in (queue, library):
        assert ".join('; ')" not in source and ".join(' ; ')" not in source              # no hand-written semicolon separator left
    assert queue.count("joined(") == 2 and "list(r.learned" in library
    i18n = (UI.parents[1] / "i18n.tsx").read_text(encoding="utf-8")
    assert "list: (items) => joinList(items, lang === 'fr')" in i18n
    got = _node_route("""({ en: m.joinList(['a', 'b', 'c'], false), fr: m.joinList(['a', 'b', 'c'], true), one: m.joinList(['a'], true),
      none: m.joinList([], true) })""", module="typography")
    nb = chr(0xA0)
    assert got == {"en": "a; b; c", "fr": f"a{nb}; b{nb}; c", "one": "a", "none": ""}


def test_every_loading_message_is_announced_to_screen_readers():
    # DOC474.245: the Rules, Dashboard and History pages showed "Loading…" in a plain paragraph nobody was told about
    pages = UI.parents[1] / "pages"
    for name in ("Rules", "Dashboard", "History"):
        src = (pages / f"{name}.tsx").read_text(encoding="utf-8")
        line = next(l for l in src.splitlines() if "t('common.loading')" in l)
        assert 'role="status"' in line, name


def test_the_confidence_colours_use_the_cut_offs_of_the_filing_thresholds():
    # DOC474.259: 0.95 and 0.8 were written in the component; they are the engine's auto / confirm thresholds, now served by
    # /api/thresholds. The only numbers left on the screen are the defaults used until the server answers: same as the file.
    from docflow.config import load_config
    thresholds = load_config().settings["thresholds"]
    bits = BITS.read_text(encoding="utf-8")
    api = (BITS.parents[1] / "api.ts").read_text(encoding="utf-8")
    assert "thresholds.auto" in bits and "thresholds.confirm" in bits and "0.95" not in bits and "0.8" not in bits
    assert f"DEFAULT_THRESHOLDS: Thresholds = {{ auto: {thresholds['auto']}, confirm: {thresholds['confirm']} }}" in api
    assert "thresholds: () => call<Thresholds>('GET', '/api/thresholds')" in api
    queue = (BITS.parents[1] / "pages" / "Queue.tsx").read_text(encoding="utf-8")
    assert "api.thresholds().then(setThresholds)" in queue and "<Confidence item={current} thresholds={thresholds} />" in queue


def test_the_field_scores_are_a_description_list_so_each_name_is_read_with_its_value():
    # DOC474.261: names and scores were bare spans; a <dl> with <dt>/<dd> pairs them for a screen reader
    bits = BITS.read_text(encoding="utf-8")
    assert "<dl className=" in bits and "<dt className=" in bits and "<dd className={tone(item.conf[k])}>" in bits


def test_a_document_being_edited_stays_in_the_list_when_the_new_filter_does_not_contain_it():
    # DOC474.214 (rest): the filter is already in the URL, so it cannot be refused; what was typed must not be thrown away
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text(encoding="utf-8")
    assert "const edited = stay && dirtyRef.current && keep != null && !fetched.some((i) => i.id === keep)" in queue
    assert "const list = edited ? [edited, ...fetched] : fetched" in queue and "itemsRef.current.find((i) => i.id === keep)" in queue
    assert "if (edited) setNote({ ok: true, text: tRef.current('queue.keptOutside') })" in queue
    assert "[group])  // not [t]" in queue                                   # a language switch must not reload the list


def test_the_release_notes_have_a_tab_a_route_and_a_screen():
    # the notes live in CHANGELOG.md; the web page shows them under their own tab
    src = UI.parents[1]
    app = (src / "App.tsx").read_text(encoding="utf-8")
    assert '<TabsTrigger value="notes">{t(\'nav.notes\')}</TabsTrigger>' in app and '<TabsContent value="notes"' in app
    assert "'notes'" in (src / "route.ts").read_text(encoding="utf-8") and "changelog: (lang: string) => call<Release[]>('GET', `/api/changelog?${new URLSearchParams({ lang })}`)" in (src / "api.ts").read_text(encoding="utf-8")
    page = (src / "pages" / "Notes.tsx").read_text(encoding="utf-8")
    assert "dangerouslySetInnerHTML" not in page                     # the text is turned into elements, never injected as HTML
    assert 'role="status"' in page and 'role="alert"' in page        # loading and failure are announced like on the other pages


def test_the_model_versus_rules_disagreement_notes_have_a_french_translation_by_prefix():
    # DOC474.155: the two notes carry values after a prefix ending in ": ", translated by the prefix like the others
    i18n = (UI.parents[1] / "i18n.tsx").read_text(encoding="utf-8")
    for what in ("date", "amount"):
        assert f"'The model and the rules read a different {what} (model / rules): '" in i18n


def test_a_batch_that_stopped_at_the_limit_says_how_many_automatic_documents_remain():
    # DOC474.20: "approve all (auto)" files at most MAX_BATCH per request; the screen must say there are more, not look finished
    src = UI.parents[1]
    queue = (src / "pages" / "Queue.tsx").read_text(encoding="utf-8")
    assert "remaining?: number" in (src / "api.ts").read_text(encoding="utf-8")
    assert "if (r.remaining) text += ` ${t('queue.moreToApprove', { n: r.remaining })}`" in queue
    i18n = (src / "i18n.tsx").read_text(encoding="utf-8")
    assert i18n.count("'queue.moreToApprove.one'") == 2 and i18n.count("'queue.moreToApprove.other'") == 2   # en + fr, singular + plural


def test_a_first_run_opens_the_settings_screen_where_the_folders_are_chosen():
    # product: nobody edits a YAML file to say where the inbox is; the tool asks
    src = UI.parents[1]
    app = (src / "App.tsx").read_text(encoding="utf-8")
    assert "if (!s.configured) window.location.hash = toHash({ page: 'settings', group: null })" in app and '<TabsTrigger value="settings">' in app
    page = (src / "pages" / "Settings.tsx").read_text(encoding="utf-8")
    for needle in ("api.saveSettings(", "api.folders(", "SettingsRefused", "aria-invalid", "settings.welcome", "dangerouslySetInnerHTML"):
        assert (needle in page) == (needle != "dangerouslySetInnerHTML"), needle
    assert "saveSettings: async" in (src / "api.ts").read_text(encoding="utf-8")
