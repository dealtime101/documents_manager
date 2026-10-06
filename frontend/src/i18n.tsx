// Minimal i18n: English by default, French on demand. The choice is remembered in the browser (best effort).
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { frenchSpaces } from '@/typography'

export type Lang = 'en' | 'fr'

const en = {
  'app.title': 'Documents Manager',
  'app.sessionFailed': 'Could not check the session.',
  'app.logoutFailed': 'Could not log out; the session is still open.',
  'nav.loggingOut': 'Logging out…',
  'nav.dashboard': 'Dashboard',
  'nav.queue': 'To file',
  'nav.history': 'History',
  'nav.rules': 'Rules',
  'nav.search': 'Search',
  'nav.notes': 'Release notes',
  'nav.settings': 'Settings',
  'settings.welcome': 'Welcome. Choose where your documents are: the folder to watch (the inbox) and the folder where they are filed (the library). Nothing is moved until you approve it.',
  'settings.inbox': 'Inbox (folder to watch)',
  'settings.library': 'Library (where documents are filed)',
  'settings.quarantine': 'Quarantine (duplicates)',
  'settings.extra': 'More folders to watch (one per line)',
  'settings.browse': 'Browse…',
  'settings.close': 'Close',
  'settings.up': 'Parent folder',
  'settings.useThis': 'Use this folder',
  'settings.noSub': 'No sub-folder here.',
  'settings.save': 'Save',
  'settings.saved': 'Settings saved.',
  'settings.helpQuarantine': 'Left empty, duplicates go to a folder in your own settings folder.',
  'notes.intro': 'What changed in each version, newest first. The notes are written in French.',
  'notes.none': 'No release notes found.',
  'notes.version': 'Version {v}',
  'notes.current': 'Latest',
  'search.hint': 'Search the text of the documents already filed. Accents and capital letters do not matter; every word must be in the document.',
  'search.label': 'Words to look for',
  'search.go': 'Search',
  'search.none': 'No filed document contains all these words.',
  'search.count.one': '{n} document found',
  'search.count.other': '{n} documents found',
  'search.open': 'Open',
  'search.openLabel': 'Open {name}',
  'rules.intro': 'What the program learned from the corrections made. Hand-written rules are not listed: they stay in the configuration files, which the program never changes.',
  'rules.aliases': 'Recognised companies',
  'rules.aliasesHelp': 'Text found at the top of a document that identifies a company.',
  'rules.types': 'Default document types',
  'rules.typesHelp': 'The type proposed for a company when nothing more precise is found.',
  'rules.routes': 'Default destinations',
  'rules.routesHelp': 'The folder proposed for a company.',
  'rules.none': 'Nothing learned yet.',
  'rules.filed.one': '{n} document filed',
  'rules.filed.other': '{n} documents filed',
  'rules.forget': 'Forget',
  'rules.forgetLabel': 'Forget the rule of {company}',
  'rules.forgetPatternLabel': 'Forget the pattern "{pattern}" of {company}',
  'rules.confirmForget': 'Forget the rule of {what}? Documents already filed stay where they are.',
  'rules.forgotten': 'Rule forgotten.',
  'rules.save': 'Save',
  'rules.destinationOf': 'Destination of {company}',
  'rules.routeSaved': 'Destination corrected.',
  'nav.logout': 'Log out',
  'lang.label': 'Language',
  'login.username': 'Username',
  'login.password': 'Password',
  'login.submit': 'Sign in',
  'login.busy': 'Signing in…',
  'status.auto': 'Automatic',
  'status.confirm': 'To confirm',
  'status.manual': 'Manual',
  'status.duplicate': 'Duplicate',
  'status.logical_duplicate': 'Possible duplicate',
  'status.error': 'Error',
  'conf.global': 'Overall confidence',
  'conf.high': 'high confidence',
  'conf.medium': 'medium confidence, to check',
  'conf.low': 'low confidence',
  'field.date': 'Date',
  'field.company': 'Company',
  'field.type': 'Type',
  'field.detail': 'Detail',
  'field.amount': 'Amount',
  'field.destination': 'Destination',
  'field.currency': 'Currency',
  'field.dateFull': 'Date (YYYY-MM-DD, YYYY-MM, YYYY or XXXX)',
  'field.folder': 'Destination folder (relative to Documents)',
  'field.fileName': 'File name (leave as is to have it recalculated)',
  'queue.scan': 'Scan inbox',
  'queue.scanning': 'Analysing… {done}/{total}',
  'queue.approveAuto': 'Approve automatic ({n})',
  'queue.tick': 'Select {name}',
  'queue.minConfidence': 'Minimum confidence (%)',
  'queue.selectFrom': 'Select',
  'queue.selectSame': 'Same company and type as the open document',
  'queue.clearSelection': 'Clear selection',
  'queue.approveSelected': 'Approve selected ({n})',
  'queue.confirmBatch.one': 'Approve {n} document? It is filed as shown.',
  'queue.confirmBatch.other': 'Approve {n} documents? Each one is filed as shown.',
  'queue.empty': 'Nothing to file. Drop PDFs in the inbox, then click “Scan inbox”.',
  'queue.truncated': 'Showing {shown} of {total}. File or approve some to see the rest.',
  'queue.nameToEnter': 'Name to enter',
  'queue.noSelection': 'No document selected.',
  'queue.preview': 'Preview',
  'queue.open': 'Open document',
  'queue.approve': 'Approve',
  'queue.quarantine': 'Move to quarantine',
  'queue.save': 'Save changes',
  'queue.ignore': 'Ignore',
  'queue.remove': 'Remove from queue',
  'queue.saved': 'Changes saved.',
  'queue.filed': 'Filed.',
  'queue.quarantined': 'Duplicate moved to quarantine.',
  'queue.filtered': 'Showing only: {group}',
  'queue.keptOutside': 'This document has unsaved changes: it stays at the top of the list even though it is not in this category.',
  'queue.showAll': 'Show all',
  'queue.emptyGroup': 'No document in this category.',
  'queue.learned': 'Remembered for next time: {list}.',
  'queue.learningFailed': 'Warning: the document is filed, but your correction could not be saved as a rule.',
  'learned.company': 'company “{v}”',
  'learned.type': 'default type “{v}” for {c}',
  'learned.route': 'destination “{v}” for {c}',
  'queue.ignored': 'Ignored: it will not come back on the next scan.',
  'queue.removed': 'Removed from the queue (the file stays where it is).',
  'queue.confirmDiscard': 'You have unsaved changes on this document. Switch anyway and lose them?',
  'queue.confirmRemove': 'Remove this document from the queue? The file stays where it is and comes back at the next scan, but your edits on it are lost.',
  'queue.scanDone.one': 'Scan finished: {n} new document.',
  'queue.scanDone.other': 'Scan finished: {n} new documents.',
  'queue.scanFailed': 'The scan failed: {err}',
  'queue.moreToApprove.one': '{n} automatic document is still waiting: press the button again.',
  'queue.moreToApprove.other': '{n} automatic documents are still waiting: press the button again.',
  'queue.approvedMany.one': '{n} document filed.',
  'queue.approvedMany.other': '{n} documents filed.',
  'queue.failedMany.one': 'Failed for {n} document: {list}.',
  'queue.failedMany.other': 'Failed for {n} documents: {list}.',
  'dash.toProcess': 'Documents to process',
  'dash.today': 'Filed today',
  'dash.needsValidation': 'Needing validation',
  'dash.ready': 'Ready (automatic)',
  'dash.duplicates': 'Duplicates detected',
  'dash.errors': 'Errors',
  'dash.sources': 'Sources',
  'dash.srcInbox': 'Drop folder (_Inbox)',
  'dash.srcBacklog': 'Backlog',
  'dash.pdfCount.one': '{n} PDF',
  'dash.pdfCount.other': '{n} PDFs',
  'acc.title': 'Accuracy of the proposals',
  'acc.none': 'No document filed yet: nothing to measure.',
  'acc.summary.one': 'Accepted without any correction: {untouched} of {n} filed document ({rate}).',
  'acc.summary.other': 'Accepted without any correction: {untouched} of {n} filed documents ({rate}).',
  'acc.fields': 'Corrected by hand, by field',
  'acc.fieldCount': '{n} of {total}',
  'acc.loaded': 'Accuracy figures loaded.',
  'acc.untouchedCount': '{n} accepted of {total}',
  'acc.band': '{band}%',
  'acc.months': 'Accepted without correction, by month',
  'acc.companies': 'Companies corrected most often',
  'acc.bands': 'By confidence when proposed',
  'acc.suggest': 'Every one of the {documents} filed documents proposed with at least {suggested} confidence was accepted without correction, {fresh} of them below the current automatic threshold ({current}). This is an observation, not a guarantee: check it before lowering the threshold.',
  'acc.noSuggest': 'Not enough evidence to suggest another automatic threshold (current: {current}).',
  'dash.lastOps': 'Latest operations',
  'dash.noOps': 'No operations.',
  'dash.undone': '(undone)',
  'common.loading': 'Loading…',
  'common.retry': 'Try again',
  'dash.updated': 'Updated {at}',
  'dash.stale': 'The server did not answer the last refresh: these figures may be out of date.',
  'hist.caption': 'History of the filing operations, the latest first',
  'hist.op': 'Operation',
  'hist.from': 'From',
  'hist.to': 'To',
  'hist.undo': 'Undo',
  'hist.undone': 'Undone',
  'hist.undoOp': 'Undo operation {id} ({file})',
  'hist.actions': 'Action',
  'hist.confirmUndo': 'Undo this operation? The file gets its old name and folder back.',
  'hist.restored': 'Restored: {path}',
  'hist.none': 'No operations yet.',
  'op.move': 'move',
  'op.quarantine': 'quarantine',
} as const

export type Key = keyof typeof en
// a message with a count has one text per plural form (`name.one`, `name.other`): callers ask for `name` and pass { n }
type Asked<K> = K extends `${infer Name}.${'one' | 'other'}` ? Name : K
export type AskKey = Asked<Key>

const fr: Record<Key, string> = {
  'app.title': 'Documents Manager',
  'app.sessionFailed': 'Vérification de la session impossible.',
  'app.logoutFailed': 'Déconnexion impossible : la session est toujours ouverte.',
  'nav.loggingOut': 'Déconnexion en cours…',
  'nav.dashboard': 'Tableau de bord',
  'nav.queue': 'À classer',
  'nav.history': 'Historique',
  'nav.rules': 'Règles',
  'nav.search': 'Recherche',
  'nav.notes': 'Notes de version',
  'nav.settings': 'Réglages',
  'settings.welcome': "Bienvenue. Choisir où sont les documents : le dossier à surveiller (la boîte de réception) et le dossier où ils sont classés (la bibliothèque). Rien ne bouge avant approbation.",
  'settings.inbox': 'Boîte de réception (dossier à surveiller)',
  'settings.library': 'Bibliothèque (où les documents sont classés)',
  'settings.quarantine': 'Quarantaine (doublons)',
  'settings.extra': 'Autres dossiers à surveiller (un par ligne)',
  'settings.browse': 'Parcourir…',
  'settings.close': 'Fermer',
  'settings.up': 'Dossier parent',
  'settings.useThis': 'Utiliser ce dossier',
  'settings.noSub': 'Aucun sous-dossier ici.',
  'settings.save': 'Enregistrer',
  'settings.saved': 'Réglages enregistrés.',
  'settings.helpQuarantine': 'Laissée vide, les doublons vont dans un dossier du dossier de réglages de l\'utilisateur.',
  'notes.intro': 'Ce qui a changé à chaque version, la plus récente en premier.',
  'notes.none': 'Aucune note de version trouvée.',
  'notes.version': 'Version {v}',
  'notes.current': 'Dernière',
  'search.hint': "Chercher dans le texte des documents déjà classés. Les accents et les majuscules n'ont pas d'importance ; tous les mots doivent figurer dans le document.",
  'search.label': 'Mots à chercher',
  'search.go': 'Chercher',
  'search.none': 'Aucun document classé ne contient tous ces mots.',
  'search.count.one': '{n} document trouvé',
  'search.count.other': '{n} documents trouvés',
  'search.open': 'Ouvrir',
  'search.openLabel': 'Ouvrir {name}',
  'rules.intro': "Ce que le programme a retenu des corrections faites. Les règles écrites à la main ne figurent pas ici : elles restent dans les fichiers de configuration, que le programme ne modifie jamais.",
  'rules.aliases': 'Sociétés reconnues',
  'rules.aliasesHelp': "Texte repéré en haut d'un document qui identifie une société.",
  'rules.types': 'Types de document par défaut',
  'rules.typesHelp': "Le type proposé pour une société quand rien de plus précis n'est trouvé.",
  'rules.routes': 'Destinations par défaut',
  'rules.routesHelp': 'Le dossier proposé pour une société.',
  'rules.none': "Rien d'appris pour l'instant.",
  'rules.filed.one': '{n} document classé',
  'rules.filed.other': '{n} documents classés',
  'rules.forget': 'Oublier',
  'rules.forgetLabel': 'Oublier la règle de {company}',
  'rules.forgetPatternLabel': 'Oublier le motif « {pattern} » de {company}',
  'rules.confirmForget': 'Oublier la règle de {what} ? Les documents déjà classés ne bougent pas.',
  'rules.forgotten': 'Règle oubliée.',
  'rules.save': 'Enregistrer',
  'rules.destinationOf': 'Destination de {company}',
  'rules.routeSaved': 'Destination corrigée.',
  'nav.logout': 'Déconnexion',
  'lang.label': 'Langue',
  'login.username': 'Utilisateur',
  'login.password': 'Mot de passe',
  'login.submit': 'Se connecter',
  'login.busy': 'Connexion en cours…',
  'status.auto': 'Automatique',
  'status.confirm': 'À confirmer',
  'status.manual': 'Manuel',
  'status.duplicate': 'Doublon',
  'status.logical_duplicate': 'Doublon probable',
  'status.error': 'Erreur',
  'conf.global': 'Confiance globale',
  'conf.high': 'confiance élevée',
  'conf.medium': 'confiance moyenne, à vérifier',
  'conf.low': 'confiance faible',
  'field.date': 'Date',
  'field.company': 'Société',
  'field.type': 'Type',
  'field.detail': 'Détail',
  'field.amount': 'Montant',
  'field.destination': 'Destination',
  'field.currency': 'Devise',
  'field.dateFull': 'Date (AAAA-MM-JJ, AAAA-MM, AAAA ou XXXX)',
  'field.folder': 'Dossier de destination (relatif à Documents)',
  'field.fileName': "Nom du fichier (laisser tel quel pour qu'il soit recalculé)",
  'queue.scan': "Scanner l'Inbox",
  'queue.scanning': 'Analyse… {done}/{total}',
  'queue.approveAuto': 'Approuver les automatiques ({n})',
  'queue.tick': 'Sélectionner {name}',
  'queue.minConfidence': 'Confiance minimale (%)',
  'queue.selectFrom': 'Sélectionner',
  'queue.selectSame': 'Même société et même type que le document ouvert',
  'queue.clearSelection': 'Désélectionner tout',
  'queue.approveSelected': 'Approuver la sélection ({n})',
  'queue.confirmBatch.one': 'Approuver {n} document ? Il est classé tel qu’affiché.',
  'queue.confirmBatch.other': 'Approuver {n} documents ? Chacun est classé tel qu’affiché.',
  'queue.empty': "Rien à classer. Déposer des PDF dans le dossier _Inbox, puis cliquer sur « Scanner l'Inbox ».",
  'queue.truncated': 'Affichage de {shown} sur {total}. Classer ou approuver quelques documents pour voir la suite.',
  'queue.nameToEnter': 'Nom à saisir',
  'queue.noSelection': 'Aucun document sélectionné.',
  'queue.preview': 'Aperçu',
  'queue.open': 'Ouvrir le document',
  'queue.approve': 'Approuver',
  'queue.quarantine': 'Mettre en quarantaine',
  'queue.save': 'Enregistrer les modifications',
  'queue.ignore': 'Ignorer',
  'queue.remove': 'Retirer de la file',
  'queue.saved': 'Modifications enregistrées.',
  'queue.filed': 'Classé.',
  'queue.quarantined': 'Doublon mis en quarantaine.',
  'queue.filtered': 'Affichage limité à : {group}',
  'queue.keptOutside': "Ce document a des modifications non enregistrées : il reste en tête de liste même s'il n'est pas dans cette catégorie.",
  'queue.showAll': 'Tout afficher',
  'queue.emptyGroup': 'Aucun document dans cette catégorie.',
  'queue.learned': 'Retenu pour la prochaine fois : {list}.',
  'queue.learningFailed': "Attention : le document est classé, mais la correction n'a pas pu être enregistrée comme règle.",
  'learned.company': 'société « {v} »',
  'learned.type': 'type par défaut « {v} » pour {c}',
  'learned.route': 'destination « {v} » pour {c}',
  'queue.ignored': 'Ignoré : il ne reviendra pas au prochain scan.',
  'queue.removed': 'Retiré de la file (le fichier reste en place).',
  'queue.confirmDiscard': 'Ce document a des modifications non enregistrées. Changer quand même et les perdre ?',
  'queue.confirmRemove': 'Retirer ce document de la file ? Le fichier reste en place et revient au prochain scan, mais les modifications sont perdues.',
  'queue.scanDone.one': 'Scan terminé : {n} nouveau document.',
  'queue.scanDone.other': 'Scan terminé : {n} nouveaux documents.',
  'queue.scanFailed': 'Le scan a échoué : {err}',
  'queue.moreToApprove.one': "{n} document automatique attend encore : appuyer de nouveau sur le bouton.",
  'queue.moreToApprove.other': '{n} documents automatiques attendent encore : appuyer de nouveau sur le bouton.',
  'queue.approvedMany.one': '{n} document classé.',
  'queue.approvedMany.other': '{n} documents classés.',
  'queue.failedMany.one': 'Échec pour {n} document : {list}.',
  'queue.failedMany.other': 'Échec pour {n} documents : {list}.',
  'dash.toProcess': 'Documents à traiter',
  'dash.today': "Classés aujourd'hui",
  'dash.needsValidation': 'Nécessitant validation',
  'dash.ready': 'Prêts (automatiques)',
  'dash.duplicates': 'Doublons détectés',
  'dash.errors': 'Erreurs',
  'dash.sources': 'Sources',
  'dash.srcInbox': 'Dépôt (_Inbox)',
  'dash.srcBacklog': 'Arriéré',
  'dash.pdfCount.one': '{n} PDF',
  'dash.pdfCount.other': '{n} PDF',
  'acc.title': 'Précision des propositions',
  'acc.none': "Aucun document classé pour l'instant : rien à mesurer.",
  'acc.summary.one': 'Acceptés sans aucune correction : {untouched} sur {n} document classé ({rate}).',
  'acc.summary.other': 'Acceptés sans aucune correction : {untouched} sur {n} documents classés ({rate}).',
  'acc.fields': 'Corrections faites à la main, par champ',
  'acc.fieldCount': '{n} sur {total}',
  'acc.loaded': 'Chiffres de précision chargés.',
  // the space before the % of 'acc.band' below is U+202F (narrow no-break space), the French typographic rule: keep it
  'acc.untouchedCount': '{n} acceptés sur {total}',
  'acc.band': '{band} %',
  'acc.months': 'Acceptés sans correction, par mois',
  'acc.companies': 'Sociétés corrigées le plus souvent',
  'acc.bands': 'Selon la confiance au moment de la proposition',
  'acc.suggest': "Chacun des {documents} documents classés proposés avec au moins {suggested} de confiance a été accepté sans correction, dont {fresh} sous le seuil automatique actuel ({current}). C'est une observation, pas une garantie : la vérifier avant d'abaisser le seuil.",
  'acc.noSuggest': "Pas assez d'éléments pour suggérer un autre seuil automatique (actuel : {current}).",
  'dash.lastOps': 'Dernières opérations',
  'dash.noOps': 'Aucune opération.',
  'dash.undone': '(annulée)',
  'common.loading': 'Chargement…',
  'common.retry': 'Réessayer',
  'dash.updated': 'Mis à jour : {at}',
  'dash.stale': "Le serveur n'a pas répondu au dernier rafraîchissement : ces chiffres sont peut-être périmés.",
  'hist.caption': 'Historique des opérations de classement, la plus récente en premier',
  'hist.op': 'Opération',
  'hist.from': 'De',
  'hist.to': 'Vers',
  'hist.undo': 'Annuler',
  'hist.undone': 'Annulée',
  'hist.undoOp': "Annuler l'opération {id} ({file})",
  'hist.actions': 'Action',
  'hist.confirmUndo': "Annuler cette opération ? Le fichier retrouve son ancien nom et son ancien dossier.",
  'hist.restored': 'Restauré : {path}',
  'hist.none': "Aucune opération pour l'instant.",
  'op.move': 'déplacement',
  'op.quarantine': 'quarantaine',
}

// Messages produced by the server are in English; exact texts and "prefix: detail" texts are translated here.
const frMessages: Record<string, string> = {
  'Identical document already filed (SHA-256).': 'Document identique déjà classé (SHA-256).',
  'This page is an image and Tesseract was not found: OCR is unavailable.': 'Cette page est une image et Tesseract est introuvable : OCR impossible.',
  // the former wording, still stored on items made before the change: keep translating it
  'Image page and Tesseract not found: OCR unavailable.': 'Page image et Tesseract introuvable : OCR impossible.',
  'No file name could be built: the company or the type is empty once cleaned.':
    "Aucun nom de fichier n'a pu être construit : la société ou le type est vide une fois nettoyé.",
  'OCR is disabled in the configuration: pages without text were not read.':
    "L'OCR est désactivé dans la configuration : les pages sans texte n'ont pas été lues.",
  'Analysed by local model (confirmation required).': 'Analyse par modèle local (confirmation requise).',
  'Year-based destination, but the document date is unknown.': 'Destination par année, mais la date du document est inconnue.',
  'Unexpected error.': 'Erreur inattendue (le détail est dans la console du navigateur).',
  'No destination rule.': 'Aucune règle de destination.',
  'The destination uses a placeholder that does not exist: ': "La destination utilise un gabarit qui n'existe pas : ",
  'The destination configured for this type is not usable.':"La destination configurée pour ce type n'est pas utilisable.",
  'Document potentially already present.': 'Document potentiellement déjà présent.',
  'Identical to another file in the same batch (SHA-256).': 'Identique à un fichier du même lot (SHA-256).',
  'Identical to a document already filed (SHA-256).': 'Identique à un document déjà classé (SHA-256).',
  'Identical to another file in the queue (SHA-256).': 'Identique à un autre fichier de la file (SHA-256).',
  'this item has already been handled': 'cet élément est déjà traité',
  'invalid amount': 'montant invalide',
  'the name must end with .pdf': 'le nom doit se terminer par .pdf',
  'company, type and destination are required before approving': "société, type et destination sont requis avant d'approuver",
  'file not found or outside the allowed folders': 'fichier introuvable ou hors des dossiers autorisés',
  'invalid credentials': 'identifiants invalides',
  'not found': 'introuvable',
  'unknown action': 'action inconnue',
  'file unavailable': 'fichier indisponible',
  'no operation to undo': 'aucune opération à annuler',
  'incomplete proposal: manual validation required': 'proposition incomplète : validation manuelle requise',
  'Cannot read file: ': 'Lecture impossible : ',
  'Ollama unavailable: ': 'Ollama indisponible : ',
  'value rejected: ': 'valeur refusée : ',
  'file not found: ': 'fichier introuvable : ',
  'the original location is occupied: ': "l'emplacement d'origine est occupé : ",
  'destination refused: ': 'destination refusée : ',
  'destination outside root: ': 'destination hors racine : ',
  'HTTP error: ': 'Erreur HTTP : ',
  'Network error: the server cannot be reached.': 'Erreur réseau : le serveur est injoignable.',
  'unexpected error: ': 'erreur inattendue : ',
  'Incomplete text, pages not read: ': 'Texte incomplet, pages non lues : ',
  'unexpected response from the server: ': 'réponse inattendue du serveur : ',
  'The model and the rules read a different date (model / rules): ': 'Le modèle et les règles lisent une date différente (modèle / règles) : ',
  'The model and the rules read a different amount (model / rules): ': 'Le modèle et les règles lisent un montant différent (modèle / règles) : ',
}

// the French texts are written with plain spaces; what the screen shows has the no-break ones (typography.ts)
const frSpaced = Object.fromEntries(Object.entries(fr).map(([k, v]) => [k, frenchSpaces(v)])) as Record<Key, string>
const frMessagesSpaced = Object.fromEntries(Object.entries(frMessages).map(([k, v]) => [k, frenchSpaces(v)])) as Record<string, string>

const fill = (s: string, vars?: Record<string, string | number>) =>
  s.replace(/\{(\w+)\}/g, (_, k: string) => String(vars?.[k] ?? `{${k}}`))

function readLang(): Lang {
  try {
    const stored = localStorage.getItem('docflow.lang')
    if (stored === 'fr' || stored === 'en') return stored  // a choice made with the switch always wins
  } catch { /* private mode or blocked storage: nothing saved, the browser's language decides */ }
  return navigator.language.toLowerCase().startsWith('fr') ? 'fr' : 'en'
}

interface Ctx {
  lang: Lang
  setLang: (l: Lang) => void
  t: (k: AskKey, vars?: Record<string, string | number>) => string
  msg: (serverText: string) => string
  /** A server timestamp ('2026-10-04T06:59:02', local time of the server, no zone) shown in the language of the page. */
  time: (iso: string) => string
  /** A ratio (0.95) as a percentage in the language of the page: '95 %' in French, '95%' in English. */
  percent: (ratio: number | undefined) => string
  /** A month key from the server ('2026-03') as 'mars 2026' / 'March 2026'; anything that is not such a key is shown as it is. */
  month: (key: string) => string
  /** A document date from the server ('2025-10-07', '2025-10', '2025') as '7 octobre 2025' / 'October 7, 2025'; 'XXXX' (unknown)
   *  and anything else is shown as it is. */
  date: (key: string) => string
}

const I18n = createContext<Ctx | null>(null)

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(readLang)
  // screen readers, hyphenation, spell-check and browser translation all depend on <html lang>
  useEffect(() => { document.documentElement.lang = lang }, [lang])
  const setLang = useCallback((l: Lang) => {
    setLangState(l)
    try { localStorage.setItem('docflow.lang', l) } catch { /* private mode: the choice just isn't remembered */ }
  }, [])
  const value = useMemo<Ctx>(() => {
    const locale = lang === 'fr' ? 'fr-CA' : 'en-CA'
    const clock = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' })
    const percent = new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 0 })
    const monthName = new Intl.DateTimeFormat(locale, { month: 'long', year: 'numeric', timeZone: 'UTC' })  // UTC: no day shift
    const dayName = new Intl.DateTimeFormat(locale, { dateStyle: 'long', timeZone: 'UTC' })
    const month = (key: string) => {
      const parts = /^(\d{4})-(0[1-9]|1[0-2])$/.exec(key)  // anything else (an odd key from a newer server) is shown as it is
      return parts ? monthName.format(new Date(Date.UTC(Number(parts[1]), Number(parts[2]) - 1, 1))) : key
    }
    const plural = new Intl.PluralRules(locale)  // French: 0 and 1 are 'one'; English: only 1
    const words: Record<string, string> = lang === 'fr' ? frSpaced : en
    const text = (k: string, n: unknown) =>
      (typeof n === 'number' ? words[`${k}.${plural.select(n)}`] ?? words[`${k}.other`] : undefined) ?? words[k]
    return {
      lang, setLang,
      percent: (ratio) => (ratio === undefined ? '—' : percent.format(ratio)),
      month,
      date: (key) => {
        const full = /^(\d{4})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/.exec(key)
        if (full) {
          const [, year, mon, day] = full
          const d = new Date(Date.UTC(Number(year), Number(mon) - 1, Number(day)))
          return d.getUTCDate() === Number(day) ? dayName.format(d) : key  // 2025-02-31 rolls over to March: not a date, as it is
        }
        if (/^\d{4}-\d{2}$/.test(key)) return month(key)
        return key  // 'YYYY' alone, 'XXXX' (unknown) or anything else
      },
      // the stamp has no zone: read as the browser's local time, which keeps the wall-clock time the server wrote
      time: (iso) => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? iso : clock.format(d) },
      // a key built at run time (`status.${x}`) can be missing: show the key rather than crash the whole page
      t: (k, vars) => fill(text(k, vars?.n) ?? k, vars),
      msg: (text) => {
        if (lang === 'en') return text
        if (frMessagesSpaced[text]) return frMessagesSpaced[text]
        const prefix = Object.keys(frMessagesSpaced).find((p) => p.endsWith(': ') && text.startsWith(p))
        return prefix ? frMessagesSpaced[prefix] + text.slice(prefix.length) : text
      },
    }
  }, [lang, setLang])
  return <I18n.Provider value={value}>{children}</I18n.Provider>
}

export function useI18n(): Ctx {
  const c = useContext(I18n)
  if (!c) throw new Error('useI18n outside I18nProvider')
  return c
}

export function LangSwitch() {
  const { lang, setLang, t } = useI18n()
  const cls = (l: Lang) => `px-2 py-1 text-xs font-medium ${lang === l ? 'bg-slate-900 text-white' : 'bg-white text-slate-600'}`
  return (
    <fieldset className="m-0 inline-flex min-w-0 overflow-hidden rounded-md border p-0" aria-label={t('lang.label')}>
      {/* each language names itself and is pronounced in itself (hence lang), whatever the language of the page */}
      <button type="button" className={cls('en')} onClick={() => setLang('en')} aria-pressed={lang === 'en'}
        lang="en" aria-label="English">EN</button>
      <button type="button" className={cls('fr')} onClick={() => setLang('fr')} aria-pressed={lang === 'fr'}
        lang="fr" aria-label="Français">FR</button>
    </fieldset>
  )
}
