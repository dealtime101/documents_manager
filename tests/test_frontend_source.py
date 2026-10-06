"""Source-level checks on the React components (there is no JS test runner: these read the files themselves)."""
import re
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parents[1] / "frontend" / "src" / "components" / "ui"


def test_a_badge_only_reacts_to_the_pointer_when_it_is_a_link():
    """A Badge is a static <span> unless rendered as a link: a hover effect on every variant makes a plain label look clickable."""
    source = (UI / "badge.tsx").read_text()
    variants = source[source.index("variants:"):source.index("defaultVariants")]
    classes = re.findall(r"[\w\[\]/:.\-]+", variants)
    hovers = [c for c in classes if "hover:" in c]
    assert hovers, "the variants lost every hover class: the check below would pass for nothing"
    assert [c for c in hovers if "[a]:hover:" not in c] == []             # "dark:[a]:hover:…" stacks, so "contains"


BITS = Path(__file__).resolve().parents[1] / "frontend" / "src" / "components" / "Bits.tsx"


def _status_badge(source: str) -> str:
    return source[source.index("export function StatusBadge"):source.index("const FIELDS")]


def test_a_long_status_label_is_cut_with_an_ellipsis_and_stays_readable_in_the_title():
    badge = _status_badge(BITS.read_text())
    assert 'className="truncate"' in badge and "title={label}" in badge     # visible cut + the whole text on hover
    assert "min-w-0" in badge and "shrink " in badge                         # it may shrink instead of pushing the % out
    assert "max-w-full" in (UI / "badge.tsx").read_text()



def test_history_shows_a_load_error_through_the_translator_not_as_a_raw_exception_string():
    page = (BITS.parents[1] / "pages" / "History.tsx").read_text()
    assert "setLoadError(errorText(e))" in page and "msg(loadError)" in page   # the raw server text goes through msg() when shown
    assert "setNote(String(" not in page                                     # "Error: HTTP error: 500" is not a text msg() knows


def test_history_says_no_operations_only_after_a_load_that_succeeded_and_came_back_empty():
    page = (BITS.parents[1] / "pages" / "History.tsx").read_text()
    assert "useState<Operation[] | null>(null)" in page                      # "not loaded yet" is its own state
    assert "ops?.length === 0" in page and "ops.length === 0" not in page.replace("ops?.length === 0", "")
    assert "common.loading" in page


def test_history_names_an_undone_operation_in_words_and_keeps_its_text_readable():
    page = (BITS.parents[1] / "pages" / "History.tsx").read_text()
    assert "t('hist.undone')" in page                                        # a word, not only a strike-through
    assert "text-slate-400" not in page                                      # 2.6:1 on white; slate-500 is 4.8:1


def test_each_history_undo_button_names_its_operation_and_the_action_column_has_a_header():
    page = (BITS.parents[1] / "pages" / "History.tsx").read_text()
    assert "aria-label={t('hist.undoOp'" in page                             # "Undo operation 12 (file.pdf)", not 12 × "Undo"
    assert "<th />" not in page and "hist.actions" in page                   # an empty header names nothing


def test_history_messages_go_through_the_shared_live_regions():
    page = (BITS.parents[1] / "pages" / "History.tsx").read_text()
    assert "<Notice note=" in page                                           # polite for a success, assertive for a failure
    assert 'className="rounded bg-slate-100' not in page                     # the old bare paragraph, announced by nothing


def test_history_shows_from_and_to_in_the_same_format_and_splits_on_both_separators():
    page = (BITS.parents[1] / "pages" / "History.tsx").read_text()
    assert page.count("<PathCell path=") == 2                                # one component for both columns
    paths = (BITS.parents[1] / "paths.ts").read_text()
    assert r"split(/[\\/]/)" in paths and r"lastIndexOf('\\')" in paths      # '/' and the Windows '\'


def test_history_allows_one_undo_at_a_time():
    page = (BITS.parents[1] / "pages" / "History.tsx").read_text()
    assert "disabled={undoing !== null}" in page and "if (undoing !== null" in page   # the button AND the handler refuse a second one
    assert page.index("setUndoing(id)") < page.index("await api.undo(id)") < page.index("setUndoing(null)")


def test_the_app_shows_a_loading_status_instead_of_a_blank_page_while_the_session_is_checked():
    app = (BITS.parents[1] / "App.tsx").read_text()
    assert "if (auth === null) return null" not in app
    assert "role=\"status\"" in app and "t('common.loading')" in app


def test_a_failed_session_check_is_an_error_with_a_retry_not_a_logout():
    app = (BITS.parents[1] / "App.tsx").read_text()
    assert ".catch(() => setAuth(false))" not in app                         # /auth/me answers 200 for an anonymous visitor
    assert "t('app.sessionFailed')" in app and "t('common.retry')" in app and 'role="alert"' in app


def test_a_failed_logout_is_reported_and_never_an_unhandled_rejection():
    app = (BITS.parents[1] / "App.tsx").read_text()
    assert "api.logout().then(refresh)" not in app                           # a rejection with nobody to catch it
    assert ".catch(() => setLogoutFailed(true))" in app and "t('app.logoutFailed')" in app


def test_every_tab_has_a_tabpanel_inside_the_same_tabs_root():
    app = (BITS.parents[1] / "App.tsx").read_text()
    assert app.count("<Tabs ") == 1 and app.count("</Tabs>") == 1            # one root around the tab list AND the pages
    for page in ("dashboard", "queue", "history"):
        assert f'<TabsTrigger value="{page}">' in app and f'<TabsContent value="{page}"' in app


def _node_route(expression: str, module: str = "route", setup: str = ""):
    """Run frontend/src/route.ts itself (transpiled with the project's own TypeScript), so the URL logic is tested, not read."""
    import json
    import shutil
    import subprocess

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
    done = subprocess.run([node, "-e", code], capture_output=True, text=True)
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


def test_the_app_follows_the_hash_and_navigation_writes_it():
    app = (BITS.parents[1] / "App.tsx").read_text()
    assert "addEventListener('hashchange'" in app and "removeEventListener('hashchange'" in app
    assert "window.location.hash = toHash(route)" in app and "useState<Page>" not in app


def test_login_sends_one_request_at_a_time_and_shows_that_it_is_working():
    page = (BITS.parents[1] / "pages" / "Login.tsx").read_text()
    assert "if (busy) return" in page and "disabled={busy}" in page and "t(busy ? 'login.busy'" in page
    assert page.index("setBusy(true)") < page.index("await api.login") < page.index("setBusy(false)")


def test_login_clears_the_previous_error_before_a_new_attempt():
    page = (BITS.parents[1] / "pages" / "Login.tsx").read_text()
    assert page.index("setErr('')") < page.index("await api.login")           # not left on screen during the next attempt


def test_a_failed_login_is_announced_and_tied_to_the_fields():
    page = (BITS.parents[1] / "pages" / "Login.tsx").read_text()
    assert 'id="login-error" role="alert"' in page                           # the region exists before the text does
    assert "'aria-describedby': 'login-error'" in page and "'aria-invalid': true" in page     # (invalid only on a refusal: DOC474.201)
    assert page.count("{...invalid}") == 2                                   # both fields


def test_a_network_failure_reaches_the_screens_as_a_translatable_api_error_not_a_raw_typeerror():
    api = (BITS.parents[1] / "api.ts").read_text()
    assert "throw new ApiError('Network error: the server cannot be reached.')" in api   # fetch's "Failed to fetch" never escapes
    assert "'Network error: the server cannot be reached.': 'Erreur réseau" in (BITS.parents[1] / "i18n.tsx").read_text()


def test_both_login_fields_are_required_so_an_empty_form_is_not_sent():
    page = (BITS.parents[1] / "pages" / "Login.tsx").read_text()
    assert page.count(" required ") == 2 and "autoComplete=\"username\"" in page and "autoComplete=\"current-password\"" in page


def test_the_login_card_shrinks_on_a_phone_instead_of_overflowing():
    page = (BITS.parents[1] / "pages" / "Login.tsx").read_text()
    assert '<Card className="w-full max-w-sm">' in page and "w-96" not in page   # 384 px fixed was wider than a 360 px phone
    assert "px-4" in page                                                          # a gutter on both sides


def test_a_disabled_input_can_show_its_not_allowed_cursor():
    source = (UI / "input.tsx").read_text()
    assert "disabled:cursor-not-allowed" in source
    assert "disabled:pointer-events-none" not in source                      # it would stop the pointer reaching the field


def test_ui_components_get_cn_from_the_one_local_module():
    """src/lib/utils.ts is where the project chooses its class-merging helper (shadcn's own `cn` package today)."""
    assert (UI.parents[1] / "lib" / "utils.ts").read_text().strip() == 'export { cn } from "cn"'
    direct = [p.name for p in UI.glob("*.tsx") if 'from "cn"' in p.read_text()]
    assert direct == []                                                      # changing the helper is then a one-line change
    assert all('import { cn } from "@/lib/utils"' in p.read_text() for p in UI.glob("*.tsx") if "cn(" in p.read_text())


def test_the_cn_helper_merges_conflicting_tailwind_classes_the_way_the_components_rely_on():
    """Components override each other's classes (TabsContent text-sm -> text-base, StatusBadge shrink-0 -> shrink)."""
    import json
    import shutil
    import subprocess

    import pytest
    frontend = UI.parents[2]
    if not shutil.which("node") or not (frontend / "node_modules" / "cn").exists():
        pytest.skip("node or the frontend's node_modules is not available")
    code = ("import('cn').then(({cn}) => console.log(JSON.stringify([cn('px-2 py-1 text-sm', 'px-4 text-base'),"
            " cn('shrink-0', 'shrink'), cn('hover:bg-muted', 'hover:bg-primary', 'dark:hover:bg-muted/50'), cn('a', false, null, 'b')])))")
    done = subprocess.run(["node", "-e", code], capture_output=True, text=True, cwd=frontend)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == ["py-1 px-4 text-base", "shrink", "hover:bg-primary dark:hover:bg-muted/50", "a b"]


def test_the_language_switch_is_named_through_the_translator():
    source = (BITS.parents[1] / "i18n.tsx").read_text()
    assert "aria-label={t('lang.label')}" in source and 'aria-label="Language"' not in source
    assert "'lang.label': 'Language'" in source and "'lang.label': 'Langue'" in source


def test_the_queue_has_one_live_region_that_is_never_unmounted():
    page = (BITS.parents[1] / "pages" / "Queue.tsx").read_text()
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
    keys = [k for k in re.findall(r"t\('([\w.]+)'", "".join(p.read_text() for p in (UI.parents[1]).rglob("*.tsx")))
            if k.rsplit(".", 1)[-1] in ("loading", "retry")]
    assert keys and set(keys) == {"common.loading", "common.retry"}          # no second "Retry" / "Try again" wording


def test_file_names_and_folders_are_cut_on_both_separators():
    got = _node_route("""({ posix: [m.baseName('/a/b/c.pdf'), m.dirName('/a/b/c.pdf')],
      windows: [m.baseName('D:\\\\Docs\\\\Factures\\\\c.pdf'), m.dirName('D:\\\\Docs\\\\Factures\\\\c.pdf')],
      mixed: [m.baseName('C:/In\\\\x.pdf'), m.dirName('C:/In\\\\x.pdf')],
      bare: [m.baseName('c.pdf'), m.dirName('c.pdf')], root: [m.baseName('/c.pdf'), m.dirName('/c.pdf')] })""", module="paths")
    assert got["posix"] == ["c.pdf", "/a/b"] and got["windows"] == ["c.pdf", "D:\\Docs\\Factures"]
    assert got["mixed"] == ["x.pdf", "C:/In"] and got["bare"] == ["c.pdf", ""] and got["root"] == ["c.pdf", "/"]


def test_field_keeps_an_id_the_caller_gave_its_input():
    source = BITS.read_text()
    assert "children.props.id ?? generated" in source                        # the caller's id wins over the generated one
    assert "<Label htmlFor={id}>" in source and "cloneElement(children, { id })" in source   # label and input share THAT id


def test_logout_sends_one_request_at_a_time_and_shows_that_it_is_working():
    app = (BITS.parents[1] / "App.tsx").read_text()
    assert "if (loggingOut) return" in app and "disabled={loggingOut}" in app and "t(loggingOut ? 'nav.loggingOut'" in app
    assert ".finally(() => setLoggingOut(false))" in app                       # released on success AND failure: it can be retried


@pytest.mark.parametrize("name", ["card", "input", "label"])
def test_components_that_use_react_only_for_its_types_import_it_as_a_type(name):
    first = (UI / f"{name}.tsx").read_text().splitlines()[0]
    assert first == 'import type * as React from "react"'                    # nothing of React is used at run time (new JSX transform)


def test_the_entry_point_checks_for_its_root_element_instead_of_asserting_it():
    main = (UI.parents[1] / "main.tsx").read_text()
    assert "getElementById('root')!" not in main                              # a non-null assertion hides a missing element
    assert "if (!root) throw new Error(" in main and "createRoot(root)" in main


def test_every_queue_action_returns_the_message_it_shows():
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text()
    assert "fn: () => Promise<string>" in queue and "string | void" not in queue   # tsc -b makes each caller return its text


def test_the_queue_save_action_takes_its_item_and_form_instead_of_asserting_them():
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text()
    assert "const save = (item: Item, values: Form) =>" in queue and "onClick={() => save(current, form)}" in queue
    assert "api.save(item.id, payload(values))" in queue and "api.save(current!.id, payload(form!))); return" not in queue


def test_the_queue_approve_action_takes_its_item_and_form_and_saves_an_edit_first():
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text()
    assert "const approve = (item: Item, values: Form) =>" in queue and "onClick={() => approve(current, form)}" in queue
    body = queue[queue.index("const approve = "):queue.index("const approveAuto")]
    assert body.index("api.save(item.id") < body.index("api.approve(item.id)")     # an edit is saved BEFORE the approval
    assert "!" not in re.sub(r"!==|!=|=>|\|\||&&|'[^']*'", "", body.split("=> run(")[0])   # and no non-null assertion in the signature


def test_the_queue_form_setter_updates_from_the_latest_state_without_an_assertion():
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text()
    setter = queue[queue.index("const set = (k: keyof Form)"):queue.index("return (\n    // One column")]
    assert "setForm((f) => (f ? { ...f, [k]: value } : f))" in setter and "form!" not in setter
    assert "const value = e.target.value" in setter                          # read before the updater runs


def test_the_approval_message_is_built_from_a_list_of_sentences_not_by_concatenation():
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text()
    body = queue[queue.index("const approve = "):queue.index("const approveAuto")]
    assert "const sentences = [t('queue.filed')]" in body and "sentences.join(' ')" in body
    assert "t('queue.filed') +" not in body


def test_the_font_licence_travels_with_the_font_files_the_interface_serves():
    """Geist is under the SIL Open Font License: bundling it in an application is allowed, provided each copy of the font
    comes with the copyright notice and the licence. The text is in public/, so the build copies it next to the fonts."""
    licence = (UI.parents[2] / "public" / "fonts-LICENSE-Geist-OFL-1.1.txt").read_text()
    assert "SIL Open Font License, Version 1.1" in licence and "The Geist Project Authors" in licence
    package = (UI.parents[2] / "node_modules" / "@fontsource-variable" / "geist" / "LICENSE")
    if package.exists():
        assert licence == package.read_text()                                  # it is the package's own text, not a rewrite


def test_the_queue_offers_tick_boxes_and_a_batch_approval_for_items_that_can_be_filed_as_they_stand():
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text()
    # DOC474.144: not duplicates, not manual, not errors, AND with a name and a destination (the server refuses the others)
    assert "const approvable = (i: Item) => (i.status === 'auto' || i.status === 'confirm') && !!i.final_name && !!i.rel_dir" in queue
    assert "type=\"checkbox\"" in queue and "t('queue.tick'" in queue and "disabled={busy || !approvable(i)}" in queue
    assert "api.approveSelected(ticks.map((i) => i.id))" in queue and "confirm(t('queue.confirmBatch'" in queue
    assert "setTicked(new Set())" in queue                                                          # the selection does not outlive its approval
    api = (UI.parents[1] / "api.ts").read_text()
    assert "'/api/items/approve-selected', { ids }" in api


def test_the_rules_screen_is_a_page_of_the_application_and_changes_only_learned_rules_with_confirmation():
    got = _node_route("({ rules: m.parseHash('#rules'), write: m.toHash({ page: 'rules', group: null }), groupIgnored: m.parseHash('#rules/duplicates') })")
    assert got["rules"] == {"page": "rules", "group": None} and got["write"] == "#rules"
    assert got["groupIgnored"] == {"page": "rules", "group": None}
    app = (UI.parents[1] / "App.tsx").read_text()
    assert '<TabsTrigger value="rules">' in app and '<TabsContent value="rules"' in app
    page = (UI.parents[1] / "pages" / "Rules.tsx").read_text()
    # forgetting asks first, and the question names the company (and the pattern) that would be forgotten (DOC474.243)
    assert "confirm(t('rules.confirmForget', { what: pattern ? `${company} / “${pattern}”` : company }))" in page
    assert "aria-label={pattern ? t('rules.forgetPatternLabel'" in page and ": t('rules.forgetLabel'" in page   # named, per pattern too
    assert "aria-label={t('rules.destinationOf'" in page                                                      # every control is named
    assert "<Notice note={shownNote} />" in page and "reloadError ?" in page   # results through the live regions (a failed reload too)
    api = (UI.parents[1] / "api.ts").read_text()
    assert "'/api/rules/forget'" in api and "'/api/rules/route'" in api


def test_the_dashboard_shows_the_accuracy_card_with_the_observation_worded_as_one():
    card = (UI.parents[1] / "components" / "Accuracy.tsx").read_text()
    assert "api.stats()" in card and "t('acc.suggest'" in card and "t('acc.noSuggest'" in card
    assert "aria-hidden=\"true\"" in card                                      # the bars are decoration: the numbers carry the meaning
    assert "<Accuracy />" in (UI.parents[1] / "pages" / "Dashboard.tsx").read_text()
    source = (UI.parents[1] / "i18n.tsx").read_text()
    assert source.count("This is an observation, not a guarantee") == 1 and source.count("pas une garantie") == 1


def test_the_search_screen_marks_the_words_found_as_elements_and_never_as_html():
    got = _node_route("({ search: m.parseHash('#search'), write: m.toHash({ page: 'search', group: null }) })")
    assert got["search"] == {"page": "search", "group": None} and got["write"] == "#search"
    page = (UI.parents[1] / "pages" / "Search.tsx").read_text()
    assert "dangerouslySetInnerHTML" not in page and "<mark" in page                      # a snippet is document text: elements only
    assert 'role="status"' in page and 'role="alert"' in page                              # count and errors are announced
    assert "api.search(query)" in page and "aria-label={t('search.openLabel'" in page
    api = (UI.parents[1] / "api.ts").read_text()
    assert "new URLSearchParams({ q })" in api                                             # the query is encoded, not concatenated
    assert '<TabsTrigger value="search">' in (UI.parents[1] / "App.tsx").read_text()


def test_declining_the_bulk_confirmation_changes_nothing():
    # DOC474.31: the confirm() sits BEFORE run(), so a "Cancel" neither reloads the list nor resets the selection or the form
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text()
    body = queue[queue.index("const approveSelected"):queue.index("const autoCount")]
    assert body.index("confirm(") < body.index("run(")
    assert "return ''" not in body


def test_bulk_approvals_ask_before_dropping_an_edit_and_keep_the_current_item():
    # DOC474.32: like select(), a bulk action confirms when the form is dirty, and reloads keeping the current item
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text()
    for name, end in (("const approveAuto", "const approveSelected"), ("const approveSelected", "const autoCount")):
        body = queue[queue.index(name):queue.index(end)]
        assert "keepEdit()" in body and "run(" in body and ", sel)" in body, name
    assert "const keepEdit = () => !dirty || confirm(t('queue.confirmDiscard'))" in queue


def test_the_sidebar_focus_ring_reaches_3_to_1_on_its_background_in_both_themes():
    # DOC474.97 (WCAG 1.4.11): a grey oklch(L 0 0) has a relative luminance of about L**3
    css = (UI.parents[1] / "index.css").read_text()

    def grey(block: str, name: str) -> float:
        found = re.search(rf"{name}:\s*oklch\(([\d.]+) 0 0\)", block)
        assert found, name
        return float(found.group(1)) ** 3

    light, dark = css[css.index(":root {"):css.index(".dark {")], css[css.index(".dark {"):css.index("@layer base")]
    for theme in (light, dark):
        ring, bg = grey(theme, "--sidebar-ring"), grey(theme, "--sidebar")
        hi, lo = max(ring, bg), min(ring, bg)
        assert (hi + 0.05) / (lo + 0.05) >= 3, theme[:6]


def test_the_notice_live_regions_are_never_hidden_while_empty():
    # DOC474.108: `empty:hidden` is display:none on the empty region, which removes it from the accessibility tree: it comes
    # back together with its text, the very case the "always in the page" comment is there to avoid
    bits = (UI.parents[0] / "Bits.tsx").read_text()
    notice = bits[bits.index("export function Notice"):bits.index("const STATUS_CLASS")]
    assert 'role="status"' in notice and 'role="alert"' in notice and "empty:hidden" not in notice


def test_the_login_error_region_is_never_hidden_while_empty():
    # DOC474.129: `empty:hidden` is display:none, so the region left the accessibility tree and a failed login was not announced
    page = (BITS.parents[1] / "pages" / "Login.tsx").read_text()
    region = page[page.index('id="login-error"'):page.index("</div>", page.index('id="login-error"'))]
    assert 'role="alert"' in region and "empty:hidden" not in region


def test_a_ticked_item_that_stops_being_approvable_leaves_the_selection():
    # DOC474.145: an item that turned into a duplicate or an error after a reload stayed ticked and was sent to the batch
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text()
    assert queue.index("const approvable = ") < queue.index("setTicked((t) => new Set(list")   # defined before load() uses it
    assert "list.filter((i) => t.has(i.id) && approvable(i))" in queue          # on every reload (also the polled ones go through load)
    assert "const ticks = items.filter((i) => ticked.has(i.id) && approvable(i))" in queue   # and again where the count and the call are made


def test_the_csrf_cookie_value_is_everything_after_the_name_not_the_text_before_the_next_equals_sign():
    # DOC474.165: split('=')[1] cut a value that contains "=" (base64-like) at its first "="
    api = (UI.parents[1] / "api.ts").read_text()
    csrf = api[api.index("function csrf()"):api.index("/** Every readable string")]
    assert ".split('=')[1]" not in csrf and "c.slice('csrftoken='.length)" in csrf


def test_an_older_dashboard_answer_never_overwrites_a_newer_one():
    # DOC474.176: the visibility refresh can overlap the scheduled one; a late OLD answer replaced the newest counters
    page = (UI.parents[1] / "pages" / "Dashboard.tsx").read_text()
    body = page[page.index("const fetchNow"):page.index("const load = ")]
    assert "const mine = ++latest.current" in body                              # every request takes a number first
    assert body.index("await api.dashboard()") < body.index("if (mine !== latest.current) return")   # a stale answer is dropped
    assert body.index("if (mine !== latest.current) return") < body.index("setD(fresh)")
    assert "const latest = useRef(0)" in page


def test_the_scan_refresh_reselects_when_the_selected_item_left_the_list_and_forgets_its_tick():
    # DOC474.33: only "nothing selected" triggered a reselection; an item filed elsewhere left an empty panel next to a full list
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text()
    tick = queue[queue.index("const tick = async"):queue.index("timer = setTimeout(tick, 3000)")]
    assert "selRef.current === null || !list.some((i) => i.id === selRef.current)" in tick
    assert "!dirtyRef.current" in tick                                           # never over a form the user has edited
    assert "setTicked((t) => new Set(list.filter((i) => t.has(i.id) && approvable(i)).map((i) => i.id)))" in tick
    assert "dirtyRef.current = !!dirty" in queue


def test_an_empty_or_out_of_range_confidence_threshold_selects_nothing():
    # DOC474.34: Number('') is 0, so an emptied field ticked every approvable item, whatever its confidence
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text()
    assert "const minValid = minConf.trim() !== '' && Number.isFinite(Number(minConf)) && Number(minConf) >= 0 && Number(minConf) <= 100" in queue
    assert "const selectFrom = () => minValid && tick(" in queue
    assert "disabled={busy || !items.length || !minValid} onClick={selectFrom}" in queue


def test_each_api_type_has_its_own_doc_comment_directly_above_it():
    # DOC474.58: two JSDoc blocks in a row, the first one (about Group) sat above Batch's comment and documented nothing
    api = (UI.parents[1] / "api.ts").read_text()
    assert not re.search(r"\*/\n/\*\*", api), "two doc comments follow each other"
    assert re.search(r"/\*\* The four disjoint categories[^\n]*\*/\nexport type Group =", api)
    assert re.search(r"/\*\* The answer of a bulk approval[^\n]*\*/\nexport type Batch =", api)


def test_the_search_runs_on_submit_only_and_never_while_a_search_is_in_flight():
    # DOC474.60 feared stale answers from searches fired while typing; there is one request at a time, started by a submit
    page = (UI.parents[1] / "pages" / "Search.tsx").read_text()
    submit = page[page.index("const submit"):page.index("return (", page.index("const submit"))]
    assert "if (busy || !query.trim()) return" in submit and submit.index("if (busy") < submit.index("api.search")
    assert page.count("api.search(") == 1                                              # the only caller: submit
    assert "onChange={(e) => setQuery(e.target.value)}" in page                       # typing only edits the text...
    assert "onSubmit={submit}" in page and "disabled={busy || !query.trim()}" in page      # ...and the button is off while busy


def test_the_total_count_header_is_a_whole_number_or_null_never_nan_or_zero_from_an_empty_string():
    # DOC474.61: Number('') is 0 and Number('abc') is NaN; `total ?? data.length` replaces neither
    api = (UI.parents[1] / "api.ts").read_text()
    start = api.index("const total = r.headers.get('X-Total-Count')")
    body = api[start:api.index("\n}", start)]                                       # up to the end of request(), return included
    assert "/^\\d+$/.test(total)" in body                                           # digits only, so '', ' ', 'abc', '-1', '1.5' are out
    assert "Number(total)" in body and "null" in body


def test_the_dashboard_comment_does_not_promise_that_two_requests_are_never_in_flight_together():
    # DOC474.77: the visibility refresh can overlap the scheduled one; what is promised is that a stale answer is ignored
    page = (UI.parents[1] / "pages" / "Dashboard.tsx").read_text()
    assert "never in flight together" not in page
    assert "const mine = ++latest.current" in page and "if (mine !== latest.current) return" in page    # the real guarantee


def test_a_network_failure_reaches_the_screens_as_a_translated_api_error_never_as_a_raw_typeerror():
    # DOC474.78 feared "TypeError: Failed to fetch" in English on the dashboard: request() converts the fetch rejection first
    api = (UI.parents[1] / "api.ts").read_text()
    body = api[api.index("async function request"):api.index("const data = await r.json()")]
    assert "r = await fetch(" in body and "catch {" in body                                    # the rejection is caught here...
    assert "throw new ApiError('Network error: the server cannot be reached.')" in body        # ...and becomes an ApiError
    assert body.index("r = await fetch(") < body.index("catch {") < body.index("throw new ApiError('Network error")


def test_the_dashboard_comment_says_the_today_tile_opens_the_unfiltered_history():
    # DOC474.79: "each tile opens exactly what it counts" was not true of the "Filed today" tile
    page = (UI.parents[1] / "pages" / "Dashboard.tsx").read_text()
    assert "each tile opens exactly what it counts" not in page
    assert "newest first" in page and "not filtered by date" in page


def test_a_dashboard_tile_is_a_button_made_of_inline_elements_only():
    # DOC474.80: Card, CardHeader and CardContent render <div>s; a <button> may only hold phrasing content
    page = (UI.parents[1] / "pages" / "Dashboard.tsx").read_text()
    start = page.index("<button key={label}")
    tile = page[start:page.index("</button>", start)]
    assert "<Card" not in tile and "<div" not in tile and "<h" not in tile
    assert tile.count("<span") >= 3 and "{t(label)}" in tile and "{n}" in tile


def test_an_operation_kind_the_front_end_does_not_know_is_shown_as_its_own_name_not_as_a_raw_key():
    # DOC474.81: t(`op.${kind}` as AskKey) printed "op.xxx" for a kind added by the server, and the cast hid it from the compiler
    src = UI.parents[1]
    ops = (src / "ops.ts").read_text()
    assert "Record<string, AskKey>" in ops and "'op.move'" in ops and "'op.quarantine'" in ops
    assert "Object.hasOwn(OP_KEYS, kind) ? t(OP_KEYS[kind]) : kind" in ops              # unknown kind: its own name (DOC474.110)
    for page in ("Dashboard.tsx", "History.tsx"):
        text = (src / "pages" / page).read_text()
        assert "opLabel(t, o.kind)" in text and "`op.${o.kind}`" not in text, page      # the unchecked cast is gone
    server_kinds = set(re.findall(r'add_op\(\w+, "(\w+)"', (UI.parents[3] / "backend" / "docflow" / "pipeline.py").read_text()))
    assert server_kinds and all(f"'op.{k}'" in ops for k in server_kinds), server_kinds      # every kind the server writes


def test_each_forget_button_of_an_alias_pattern_has_its_own_accessible_name():
    # DOC474.85: a company with several patterns gave several buttons all named "Forget the rule of <company>"
    root = UI.parents[1]
    rules = (root / "pages" / "Rules.tsx").read_text()
    assert "pattern ? t('rules.forgetPatternLabel', { company, pattern }) : t('rules.forgetLabel', { company })" in rules
    i18n = (root / "i18n.tsx").read_text()
    en, fr = i18n[i18n.index("const en"):i18n.index("const fr")], i18n[i18n.index("const fr"):]
    for block in (en, fr):
        assert "'rules.forgetPatternLabel'" in block and "{pattern}" in block.split("'rules.forgetPatternLabel'")[1].split("\n")[0]


def test_a_saved_destination_stays_on_screen_until_the_rules_are_reloaded():
    # DOC474.86: the draft was dropped right after the save, so the field showed the OLD destination until load() ended (and for
    # good if the reload failed)
    rules = (UI.parents[1] / "pages" / "Rules.tsx").read_text()
    save = rules[rules.index("const saveRoute"):rules.index("const filed")]
    assert "await api.setRoute(company, destination)" in save or "api.setRoute(company, destination)" in save
    assert "setDrafts" in save and save.index("api.setRoute") < save.index("setDrafts")
    assert "const loaded = await load()" in rules and "if (loaded) after?.()" in rules          # the draft goes only after a good reload
    act = rules[rules.index("const act"):rules.index("const forget")]
    assert act.index("await load()") < act.index("after?.()")
    assert "setDrafts" not in act.split("await load()")[0]                                         # and never before it


def test_a_route_destination_is_trimmed_before_it_is_compared_and_sent():
    # DOC474.87: only the "empty" test trimmed; " Bills/Hydro " was sent as typed, and a change of spaces alone counted as an edit
    rules = (UI.parents[1] / "pages" / "Rules.tsx").read_text()
    assert "disabled={busy || value.trim() === r.destination || !value.trim()} onClick={() => saveRoute(r.company, value.trim())}" in rules


def test_a_failed_reload_after_a_change_keeps_the_rules_and_the_success_message_on_screen():
    # DOC474.88: loadError replaces the whole page; a passing error after a successful save hid the list and the "saved" message
    rules = (UI.parents[1] / "pages" / "Rules.tsx").read_text()
    load = rules[rules.index("const load = "):rules.index("useEffect(() => { load() }")]
    assert "haveRules.current" in load and "setReloadError(" in load and "setLoadError(" in load      # two cases, told apart
    failure = load[load.index(".catch("):]
    assert failure.index("haveRules.current") < failure.index("setReloadError(") < failure.index("setLoadError(")   # kept list first
    assert "const haveRules = useRef(false)" in rules and "haveRules.current = true" in load
    assert "reloadError ? { ok: false, text: `${note?.ok ? `${note.text} ` : ''}${msg(reloadError)}` } : note" in rules   # both shown


def test_a_truncated_label_of_the_accuracy_screen_can_still_be_read_in_full():
    # DOC474.106: a long company name ended in an ellipsis with no tooltip: two companies starting alike could not be told apart
    accuracy = (UI.parents[1] / "components" / "Accuracy.tsx").read_text()
    assert '<span className="min-w-0 truncate" title={label}>{label}</span>' in accuracy


def test_the_accuracy_screen_announces_that_it_is_loading_and_that_the_figures_arrived():
    # DOC474.107: after "Retry" the content changed with no announcement for a screen reader
    root = UI.parents[1]
    accuracy, i18n = (root / "components" / "Accuracy.tsx").read_text(), (root / "i18n.tsx").read_text()
    assert '<p role="status" className="sr-only">' in accuracy                       # always in the page, empty or not
    status = accuracy[accuracy.index('<p role="status" className="sr-only">'):]
    status = status[:status.index("</p>")]
    assert "t('common.loading')" in status and "t('acc.loaded')" in status
    en, fr = i18n[i18n.index("const en"):i18n.index("const fr")], i18n[i18n.index("const fr"):]
    assert "'acc.loaded'" in en and "'acc.loaded'" in fr


def test_the_same_message_shown_twice_in_a_row_is_a_new_element_so_it_is_announced_again():
    # DOC474.109: React leaves the DOM alone when the text is identical, so a screen reader heard nothing the second time
    bits = (UI.parents[1] / "components" / "Bits.tsx").read_text()
    notice = bits[bits.index("export function Notice"):bits.index("const STATUS_CLASS")]
    assert "const shown = useRef(0)" in notice and "if (note !== last.current)" in notice and "shown.current += 1" in notice
    assert notice.count("key={shown.current}") == 2                                          # the success and the failure paragraph


def test_a_note_built_from_other_state_keeps_its_identity_between_renders():
    # Notice announces a "new" note when the object changes (DOC474.109): one rebuilt at every render would be re-announced each time
    pages = UI.parents[1] / "pages"
    history, rules = (pages / "History.tsx").read_text(), (pages / "Rules.tsx").read_text()
    assert "const shownNote = useMemo(" in history and "[note, loadError, msg])" in history
    assert "<Notice note={shownNote} />" in history and "<Notice note={shownNote} />" in rules
    assert "const shownNote = useMemo(" in rules and "[reloadError, note, msg]" in rules


def test_an_unknown_value_named_like_an_object_property_is_not_taken_for_a_known_one():
    # DOC474.110: 'constructor' in {...} is true (inherited from Object): a badge got a function as its class, a label a function
    src = UI.parents[1]
    bits, ops = (src / "components" / "Bits.tsx").read_text(), (src / "ops.ts").read_text()
    assert "const known = Object.hasOwn(STATUS_CLASS, status)" in bits
    assert "known ? STATUS_CLASS[status] : STATUS_CLASS.manual" in bits and "?? STATUS_CLASS.manual" not in bits
    assert "Object.hasOwn(OP_KEYS, kind) ? t(OP_KEYS[kind]) : kind" in ops and "kind in OP_KEYS" not in ops


def test_a_confidence_level_is_given_by_a_symbol_and_a_word_not_only_by_its_colour():
    # DOC474.111: green / amber / red alone leave out colour-blind readers and screen readers
    root = UI.parents[1]
    bits, i18n = (root / "components" / "Bits.tsx").read_text(), (root / "i18n.tsx").read_text()
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
    css = (src / "index.css").read_text()
    assert "chart" not in css
    used = [p.name for p in src.rglob("*.ts*") if re.search(r"(?:bg|text|fill|stroke|border|ring)-chart-\d|var\(--chart", p.read_text())]
    assert used == [], used


def test_muted_text_reaches_4_5_to_1_on_every_surface_it_is_drawn_on_in_both_themes():
    # DOC474.99 (WCAG 1.4.3, normal text): oklch(0.556) on oklch(0.97) is 4.3:1. A grey oklch(L 0 0) has a luminance of about L**3.
    css = (UI.parents[1] / "index.css").read_text()

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
    history = (UI.parents[1] / "pages" / "History.tsx").read_text()
    shown = history[history.index("const shownNote"):history.index("// one undo at a time")]
    assert "loadError ? { ok: false, text: `${note?.ok ? `${note.text} ` : ''}${msg(loadError)}` } : note" in shown
    assert "[note, loadError, msg]" in shown                                                  # (the note keeps its identity)


def test_keyboard_focus_stays_in_the_history_row_during_and_after_an_undo():
    # DOC474.118: the pressed button became disabled, then was replaced by the "undone" label: focus fell back to <body>
    history = (UI.parents[1] / "pages" / "History.tsx").read_text()
    assert 'aria-disabled={undoing !== null}' in history and not re.search(r"(?<!aria-)disabled=\{undoing", history)   # still focusable
    assert "tabIndex={-1}" in history and "id={`op-${o.id}`}" in history                                       # the row can take focus
    undo = history[history.index("const undo = "):history.index("return (", history.index("const undo = "))]
    assert undo.index("await load()") < undo.index("document.getElementById(`op-${id}`)?.focus()")             # after the reload


def test_the_undone_label_is_an_inline_block_so_the_struck_through_row_does_not_strike_it():
    # DOC474.120 feared the "Undone" label was itself struck through. A text decoration set on an ancestor is not propagated to
    # inline-block descendants (CSS Text, "atomic inline-level"): the label must stay an inline-block for that to hold
    history = (UI.parents[1] / "pages" / "History.tsx").read_text()
    assert "o.undone ? 'text-slate-500 line-through' : ''" in history                      # the row IS struck through
    assert re.search(r'<span className="inline-block [^"]*">\{t\(\'hist\.undone\'\)\}</span>', history)   # and the label escapes it


def test_a_failed_search_does_not_leave_the_results_of_the_previous_one_on_screen():
    # DOC474.121: the error appeared above the OLD list, which looked like the answer to the new query
    page = (UI.parents[1] / "pages" / "Search.tsx").read_text()
    submit = page[page.index("const submit"):page.index("return (", page.index("const submit"))]
    assert "setHits(null)" in submit.split("try {")[0], "the old results must go before the new request starts"


def test_a_failure_after_a_successful_login_is_not_shown_as_a_failed_login():
    # DOC474.131: onDone() sat inside the try: anything it threw was reported as "invalid credentials" with the session open
    page = (UI.parents[1] / "pages" / "Login.tsx").read_text()
    submit = page[page.index("const submit"):page.index("return (", page.index("const submit"))]
    assert "try { await api.login(u, p); onDone() }" not in submit
    assert "signedIn = true" in submit and "if (signedIn) onDone()" in submit
    assert submit.index("await api.login(u, p)") < submit.index("signedIn = true") < submit.index("if (signedIn) onDone()")
    assert submit.index("catch (x)") < submit.index("if (signedIn) onDone()")                       # outside the try/catch


def test_an_error_that_is_not_an_api_error_is_logged_and_shown_as_a_generic_translated_message():
    # DOC474.146 / .175 (and .78 / .130 for the network case): String(e) put a raw technical text in front of the user
    src = UI.parents[1]
    api = (src / "api.ts").read_text()
    helper = api[api.index("export function errorText"):]
    helper = helper[:helper.index("\n}\n")]
    assert "e instanceof ApiError" in helper and "console.error(e)" in helper and "'Unexpected error.'" in helper
    offenders = [p.name for p in src.rglob("*.ts*") if p.name != "api.ts" and re.search(r"String\((e|x)\)", p.read_text())]
    assert offenders == [], offenders                                          # every screen goes through the helper
    for page in ("App.tsx", "components/Accuracy.tsx", "pages/Rules.tsx", "pages/Dashboard.tsx", "pages/Search.tsx",
                 "pages/History.tsx", "pages/Login.tsx", "pages/Queue.tsx"):
        assert "errorText(" in (src / page).read_text(), page
    i18n = (src / "i18n.tsx").read_text()
    assert "'Unexpected error.':" in i18n[i18n.index("const frMessages"):]       # and its French text exists


def test_the_contrast_figures_quoted_in_the_focus_ring_comment_are_the_computed_ones():
    # DOC474.185 doubted the "4.7:1" of the --ring comment. A grey oklch(L 0 0) has a relative luminance of L**3, so on white
    # the contrast is 1.05 / (L**3 + 0.05): 0.556 -> 4.73, 0.708 -> 2.59. The comment must say what the numbers say.
    css = (UI.parents[1] / "index.css").read_text()
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
    history, i18n = (root / "pages" / "History.tsx").read_text(), (root / "i18n.tsx").read_text()
    head = history[history.index("<thead>"):history.index("</thead>")]
    assert len(re.findall(r"<th[\s>]", head)) == 6 and head.count('<th scope="col"') == 6            # all six headers carry the scope
    assert '<caption className="sr-only">{t(\'hist.caption\')}</caption>' in history
    en, fr = i18n[i18n.index("const en"):i18n.index("const fr")], i18n[i18n.index("const fr"):]
    assert "'hist.caption'" in en and "'hist.caption'" in fr


def test_only_a_refused_login_marks_the_fields_invalid_not_a_network_or_server_failure():
    # DOC474.201: any error set aria-invalid on both fields, telling assistive technology that a good password was wrong
    src = UI.parents[1]
    api, login = (src / "api.ts").read_text(), (src / "pages" / "Login.tsx").read_text()
    assert "export class ApiError extends Error {\n  status?: number" in api and "this.status = status" in api
    assert "throw new ApiError(errorMessage(data, r.status), r.status)" in api               # the HTTP status travels with the error
    assert "x instanceof ApiError && x.status === 401" in login and "setRefused(" in login
    assert "'aria-describedby': 'login-error'" in login and "...(refused ? { 'aria-invalid': true } : {})" in login
    assert "const invalid = err ? { 'aria-invalid': true" not in login


def test_a_long_badge_label_ends_in_an_ellipsis_and_can_be_read_in_full():
    # DOC474.203 feared a silently cut badge. The only Badge is the status badge: its label sits in a `truncate` span (hidden
    # overflow + ellipsis) and the badge carries the whole text as its title
    src = UI.parents[1]
    users = [p.name for p in src.rglob("*.tsx") if "<Badge" in p.read_text() and p.name != "badge.tsx"]
    assert users == ["Bits.tsx"], users
    bits = (src / "components" / "Bits.tsx").read_text()
    assert 'title={label}>' in bits and '<span className="truncate">{label}</span>' in bits


def test_changing_the_filter_keeps_the_open_document_and_what_was_typed_in_it():
    # DOC474.214: a new group reloads the list; the open document and its unsaved form survive when it is still listed
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text()
    assert "async (keep?: number | null, stay = false)" in queue
    assert "if (stay && dirtyRef.current && next?.id === keep) return" in queue
    assert "load(selRef.current, true)" in queue  # the filter effect asks to stay; a save (load(keep)) still refreshes the form


def test_each_doc_comment_of_api_ts_sits_right_above_the_type_it_describes():
    # DOC474.226 feared the Group comment above Batch: each type has its own comment, directly on top of it
    api = (UI.parents[1] / "api.ts").read_text()
    for text, decl in (("The answer of a bulk approval", "export type Batch"), ("The four disjoint categories", "export type Group")):
        line = next(l for l in api.splitlines() if text in l)
        assert api.splitlines()[api.splitlines().index(line) + 1].startswith(decl), text


def test_the_dashboard_counters_are_announced_when_they_change_not_on_every_refresh():
    # DOC474.236: the tiles refresh by themselves; a screen reader hears the new numbers, but the "updated at" line stays silent
    dash = (UI.parents[1] / "pages" / "Dashboard.tsx").read_text()
    assert """<p role="status" className="sr-only">{tiles.map(([label, n]) => `${t(label)}: ${n}`).join(', ')}</p>""" in dash
    updated = next(l for l in dash.splitlines() if "dash.updated" in l)
    assert "role=" not in updated and "aria-live" not in updated      # a timestamp that changes every 15 s must not be announced


def test_a_failed_background_refresh_of_the_dashboard_says_the_figures_may_be_old():
    # DOC474.237: after a failed quiet refresh the old numbers stayed with no sign but a discreet time
    dash = (UI.parents[1] / "pages" / "Dashboard.tsx").read_text()
    assert "if (quiet) setStale(true)" in dash and "setStale(false)" in dash          # set on a failed refresh, cleared on a good one
    assert """{stale && <p role="alert\"""" in dash and "t('dash.stale')" in dash


def test_a_row_of_tabs_wider_than_the_screen_scrolls_instead_of_being_cut_off():
    # DOC474.269: the list is h-8 = 2rem, so it follows the text size; what could still be cut was a row wider than the screen
    app = (UI.parents[1] / "App.tsx").read_text()
    assert '<TabsList className="max-w-full overflow-x-auto">' in app
    assert "group-data-horizontal/tabs:h-8" in (UI / "tabs.tsx").read_text()   # rem, not px: it grows with the user's text size


def test_french_texts_get_no_break_spaces_before_punctuation_and_inside_guillemets():
    # DOC474.30: a line must not break between « and its word, or leave a lone ":" at the start of the next line
    got = _node_route("""{
      colon: m.frenchSpaces('Total : 5'), guillemets: m.frenchSpaces('Oublier le motif « ACME » de X'),
      marks: m.frenchSpaces('Quoi ? Oui ! Bon ; non'), plain: m.frenchSpaces('Texte sans ponctuation, tout simple.'),
      none: m.frenchSpaces('http://x.org:80/a') }""", module="typography")
    assert got["colon"] == "Total : 5" and got["guillemets"] == "Oublier le motif « ACME » de X"
    assert got["marks"] == "Quoi ? Oui ! Bon ; non" and got["plain"] == "Texte sans ponctuation, tout simple."
    assert got["none"] == "http://x.org:80/a"                                  # a colon with no space before it is left alone
    i18n = (UI.parents[1] / "i18n.tsx").read_text()
    assert "lang === 'fr' ? frSpaced : en" in i18n and "frMessagesSpaced[text]" in i18n   # the screen reads the spaced copies


def test_the_lists_in_the_queue_messages_use_the_same_separator_in_both_languages():
    # DOC474.35: failures were joined with " ; ", what was learned with "; "
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text()
    assert "join(' ; ')" not in queue
    assert queue.count(".join('; ')") == 2


def test_every_loading_message_is_announced_to_screen_readers():
    # DOC474.245: the Rules, Dashboard and History pages showed "Loading…" in a plain paragraph nobody was told about
    pages = UI.parents[1] / "pages"
    for name in ("Rules", "Dashboard", "History"):
        src = (pages / f"{name}.tsx").read_text()
        line = next(l for l in src.splitlines() if "t('common.loading')" in l)
        assert 'role="status"' in line, name


def test_the_confidence_colours_use_the_cut_offs_of_the_filing_thresholds():
    # DOC474.259: 0.95 and 0.8 were written in the component; they are the engine's auto / confirm thresholds, now served by
    # /api/thresholds. The only numbers left on the screen are the defaults used until the server answers: same as the file.
    from docflow.config import load_config
    thresholds = load_config().settings["thresholds"]
    bits = BITS.read_text()
    api = (BITS.parents[1] / "api.ts").read_text()
    assert "thresholds.auto" in bits and "thresholds.confirm" in bits and "0.95" not in bits and "0.8" not in bits
    assert f"DEFAULT_THRESHOLDS: Thresholds = {{ auto: {thresholds['auto']}, confirm: {thresholds['confirm']} }}" in api
    assert "thresholds: () => call<Thresholds>('GET', '/api/thresholds')" in api
    queue = (BITS.parents[1] / "pages" / "Queue.tsx").read_text()
    assert "api.thresholds().then(setThresholds)" in queue and "<Confidence item={current} thresholds={thresholds} />" in queue


def test_the_field_scores_are_a_description_list_so_each_name_is_read_with_its_value():
    # DOC474.261: names and scores were bare spans; a <dl> with <dt>/<dd> pairs them for a screen reader
    bits = BITS.read_text()
    assert "<dl className=" in bits and "<dt className=" in bits and "<dd className={tone(item.conf[k])}>" in bits


def test_a_document_being_edited_stays_in_the_list_when_the_new_filter_does_not_contain_it():
    # DOC474.214 (rest): the filter is already in the URL, so it cannot be refused; what was typed must not be thrown away
    queue = (UI.parents[1] / "pages" / "Queue.tsx").read_text()
    assert "const edited = stay && dirtyRef.current && keep != null && !fetched.some((i) => i.id === keep)" in queue
    assert "const list = edited ? [edited, ...fetched] : fetched" in queue and "itemsRef.current.find((i) => i.id === keep)" in queue
    assert "if (edited) setNote({ ok: true, text: tRef.current('queue.keptOutside') })" in queue
    assert "[group])  // not [t]" in queue                                   # a language switch must not reload the list


def test_the_release_notes_have_a_tab_a_route_and_a_screen():
    # the notes live in CHANGELOG.md; the web page shows them under their own tab
    src = UI.parents[1]
    app = (src / "App.tsx").read_text()
    assert '<TabsTrigger value="notes">{t(\'nav.notes\')}</TabsTrigger>' in app and '<TabsContent value="notes"' in app
    assert "'notes'" in (src / "route.ts").read_text() and "changelog: () => call<Release[]>('GET', '/api/changelog')" in (src / "api.ts").read_text()
    page = (src / "pages" / "Notes.tsx").read_text()
    assert "dangerouslySetInnerHTML" not in page                     # the text is turned into elements, never injected as HTML
    assert 'role="status"' in page and 'role="alert"' in page        # loading and failure are announced like on the other pages


def test_the_model_versus_rules_disagreement_notes_have_a_french_translation_by_prefix():
    # DOC474.155: the two notes carry values after a prefix ending in ": ", translated by the prefix like the others
    i18n = (UI.parents[1] / "i18n.tsx").read_text()
    for what in ("date", "amount"):
        assert f"'The model and the rules read a different {what} (model / rules): '" in i18n


def test_a_batch_that_stopped_at_the_limit_says_how_many_automatic_documents_remain():
    # DOC474.20: "approve all (auto)" files at most MAX_BATCH per request; the screen must say there are more, not look finished
    src = UI.parents[1]
    queue = (src / "pages" / "Queue.tsx").read_text()
    assert "remaining?: number" in (src / "api.ts").read_text()
    assert "if (r.remaining) text += ` ${t('queue.moreToApprove', { n: r.remaining })}`" in queue
    i18n = (src / "i18n.tsx").read_text()
    assert i18n.count("'queue.moreToApprove.one'") == 2 and i18n.count("'queue.moreToApprove.other'") == 2   # en + fr, singular + plural


def test_a_first_run_opens_the_settings_screen_where_the_folders_are_chosen():
    # product: nobody edits a YAML file to say where the inbox is; the tool asks
    src = UI.parents[1]
    app = (src / "App.tsx").read_text()
    assert "if (!s.configured) window.location.hash = '#settings'" in app and '<TabsTrigger value="settings">' in app
    page = (src / "pages" / "Settings.tsx").read_text()
    for needle in ("api.saveSettings(", "api.folders(", "SettingsRefused", "aria-invalid", "settings.welcome", "dangerouslySetInnerHTML"):
        assert (needle in page) == (needle != "dangerouslySetInnerHTML"), needle
    assert "saveSettings: async" in (src / "api.ts").read_text()
