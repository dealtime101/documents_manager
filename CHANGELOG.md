# Documents Manager — notes de version

Format : la version la plus récente en premier ; un numéro `majeur.mineur.correctif` (le numéro est écrit une seule fois, dans
`pyproject.toml`). Mineur : fonction ou comportement nouveau. Correctif : correction seule. Majeur : changement qui demande
une action de votre part avant de démarrer.

## [0.7.0] - 2026-10-07

### Ajouté
- **Bibliothèque : recherche par nom** dans tous les dossiers (majuscules et accents ignorés) ; un clic sur un résultat ouvre son
  dossier.
- **Bibliothèque : dossiers** : créer, renommer, déplacer et supprimer un dossier.
- **Bibliothèque : fichiers** : renommer, déplacer et supprimer un fichier.
- **Bibliothèque : formulaire de classement** à droite d'un PDF (comme « À classer ») : « Lire le document et proposer » lit le
  document (OCR si c'est un scan) et propose société, type, date, détail et montant ; on corrige, le nom et le dossier sont
  recalculés, et « Appliquer » renomme et déplace le fichier. Une date saisie « 2026/02/24 » est acceptée.
- **Supprimer met dans `_Trash`** (à la racine de la bibliothèque) : on peut le ressortir en le déplaçant ; seul ce qui est déjà
  dans `_Trash` est supprimé définitivement (après confirmation). Rien n'est jamais remplacé : un nom déjà pris est refusé.
  Impossible de sortir de la bibliothèque, ni de modifier sa racine ou `_Trash` lui-même. Un document déjà classé dont le
  fichier est renommé ou déplacé garde son lien « Ouvrir le document ».

### Modifié
- Le menu du haut passe à la ligne quand il est trop large, au lieu d'afficher des flèches de défilement.

## [0.6.0] - 2026-10-07

### Ajouté
- **Onglet « Bibliothèque »** : un explorateur de fichiers du dossier Bibliothèque. On descend dans les dossiers (fil d'Ariane,
  dossier parent, actualiser), on voit la taille et la date de chaque fichier, et un clic sur un PDF l'affiche à droite (ou dans
  un nouvel onglet). Lecture seule : rien n'est déplacé, renommé ni supprimé. Impossible de sortir de la bibliothèque (`..`,
  chemin absolu, lien symbolique) ; un fichier qui n'est pas un PDF n'est proposé qu'en téléchargement.

## [0.5.1] - 2026-10-07

### Modifié
- **Date saisie à la main** : « 2026/02/24 », « 2026.02.24 », « 2026 02 24 » ou « 2026/2/4 » sont convertis automatiquement en
  « 2026-02-24 » (ou « 2026-02-04 ») au lieu d'être refusés. Seul l'ordre année en premier est lu (jamais JJ/MM ou MM/JJ,
  ambigus) ; une date qui n'existe pas reste refusée.

## [0.5.0] - 2026-10-07

### Ajouté
- **Sociétés connues livrées avec le programme** : une quarantaine d'émetteurs courants (Amazon, Apple, Netflix, HelloFresh,
  Hydro-Québec, Vidéotron, Bell, Desjardins, banques, assureurs, ministères et organismes du Québec et du Canada…) sont reconnus
  dès la première utilisation, sans rien apprendre. Les motifs évitent les mots courants (« apple », « bell » seuls). Pour
  changer la liste, copier `config/companies.yaml` dans votre dossier de données : votre copie remplace celle livrée. Ce que le
  programme apprend de vos corrections s'y ajoute comme avant.

## [0.4.3] - 2026-10-06

### Corrigé
- **Apprentissage d'une société** : quand le document contient le nom de la société (ex. « HelloFresh »), c'est ce nom qui est
  retenu comme règle, et non plus la première ligne du document (le titre d'une recette ou d'une lettre, différent à chaque fois).
  La société est alors proposée sur les documents suivants.

## [0.4.2] - 2026-10-06

### Corrigé
- Windows : un scan n'ouvre plus une fenêtre de console par page lue par l'OCR.

### Modifié
- Le scan affiche une barre de progression (en plus du compteur sur le bouton).

## [0.4.1] - 2026-10-06

### Corrigé
- Les documents mis en file quand l'OCR n'était pas disponible sont relus au scan suivant, une fois Tesseract trouvé (le message
  « OCR indisponible » restait sur eux, car un fichier inchangé n'était pas relu).

## [0.4.0] - 2026-10-06

### Ajouté
- **Tesseract (OCR) fourni dans l'exécutable** : avec le français, l'anglais et la détection d'orientation. Plus rien à installer
  pour lire les documents numérisés.

### Retiré
- Le message « OCR indisponible » quand Tesseract n'est pas installé sur la machine.

## [0.3.0] - 2026-10-06

Préparation d'une diffusion publique sous licence MIT.

### Ajouté
- **Application de bureau Windows** (`DocumentsManager.exe`, construite par `packaging/build_windows.bat`) : une fenêtre native qui
  démarre le serveur local (`127.0.0.1`, jamais le réseau) et s'ouvre déjà connectée grâce à un jeton à usage unique, sans mot de
  passe à créer. La base, les réglages et les règles vivent dans le dossier de l'utilisateur. Tesseract (OCR, avec le français, l'anglais
  et la détection d'orientation) est **fourni dans l'exécutable** : rien à installer.
- **Écran « Réglages »** : on choisit dans l'outil le dossier à surveiller, la bibliothèque, la quarantaine et d'autres dossiers
  à surveiller, avec un sélecteur de dossier et un message par champ s'il y a une erreur (dossier introuvable, inbox et
  bibliothèque confondues, quarantaine dans la bibliothèque). Ils sont enregistrés dans le dossier de l'utilisateur, pas dans
  celui du programme. À la première utilisation, cet écran s'ouvre tout seul.
- **Règles de l'utilisateur hors du programme** : ce qu'il écrit ou que le programme apprend vit dans son propre dossier
  (`%LOCALAPPDATA%\DocFlow` sous Windows, `~/.config/docflow` ailleurs). La configuration livrée est vide : plus aucune société, destination ni
  dossier de l'auteur.

- **Notes de version en anglais et en français** : l'écran suit la langue de l'interface (`CHANGELOG.en.md` et `CHANGELOG.md`).

### Retiré
- **Tout ce qui ne servait qu'au mode serveur** : connexion par mot de passe, déconnexion, limitation des essais de connexion,
  liste d'hôtes (`DOCFLOW_HOSTS`), modèles de service systemd (`deploy/`), `gunicorn`, et la commande de sauvegarde `backup`. Le
  programme n'écoute plus que `127.0.0.1` et n'a plus de mot de passe : seule la connexion par jeton du lanceur existe.

### Modifié
- **Nom du produit : Documents Manager** (titre de la page, de l'onglet du navigateur, du README et de ces notes). Le nom
  interne `docflow` (commande, dossiers, services, variables `DOCFLOW_*`) est conservé : le changer casserait votre installation.
- **Lecture des PDF : PyMuPDF (AGPL) est remplacé par PDFium** (via `pypdfium2`, Apache-2.0/BSD). Le programme ne contient plus
  aucune bibliothèque sous licence copyleft, ce qui permet de le publier sous licence MIT. PDFium n'est pas sûr en parallèle :
  tous ses appels passent par un verrou (l'OCR, la partie lente, reste en dehors). PyMuPDF ne sert plus qu'à fabriquer des PDF
  d'essai dans les tests (dépendance de développement). `scripts/make_sandbox.py` écrit ses PDF d'exemple sans aucune bibliothèque.

## [0.2.0] - 2026-10-05

Passage de correction complet (audit 474 : 457 constats, tous traités ; 311 corrigés, 101 réfutés avec preuve, le reste décidé
ou différé avec une date de revue). Rien n'est appliqué au service tant qu'il n'est pas redémarré : voir « Pour déployer ».

### Ajouté
- **Sauvegarde** : `manage.py backup` fait un instantané cohérent de la base (même pendant que le service travaille) et copie les
  règles apprises dans un dossier daté, garde les 14 plus récents, refuse d'écrire si le partage n'est pas monté ;
  `--restore` remet une sauvegarde en place. Minuteur nocturne prêt dans `deploy/`.
- **Version** : `docflow --version`, et le numéro s'affiche dans l'en-tête de l'interface.
- **Notes de version** : un onglet « Notes de version » affiche ce fichier, la version la plus récente en premier.
- **Tableau de bord** : les compteurs sont annoncés aux lecteurs d'écran quand ils changent ; un avertissement apparaît si le
  rafraîchissement automatique échoue (chiffres peut-être périmés).
- **Couleurs de confiance** : elles suivent les seuils réels du moteur (`thresholds` de `config/settings.yaml`, servis par
  `/api/thresholds`), donc une couleur ne peut plus contredire le statut si vous changez ces seuils.
- **« Tout approuver (auto) »** : traite au plus 200 documents par appui, et dit combien d'automatiques attendent encore.
- **File « À classer »** : le document ouvert et ce qui y est saisi survivent à un changement de filtre, même s'il n'est pas dans
  la nouvelle catégorie (il reste en tête de liste, avec une note) ; la confirmation d'oubli
  d'une règle nomme la société et le motif.
- **Qualité** : mypy sans erreur, ruff configuré dans `pyproject.toml`, typographie française (espaces insécables).

### Corrigé
- **Classement** : un fichier ne reste plus en double si la suppression de la source échoue ; une copie inter-volumes
  interrompue ne laisse plus de fichier partiel ; noms réservés Windows, points et espaces finaux refusés ; montants (signe,
  devise, entiers, fractions) mieux lus ; abréviations françaises des mois ; « overdue » et « residue » ne sont plus pris pour
  une échéance ; une société ou un détail écrits dans un autre alphabet (cyrillique, grec, arabe, caractères CJK) sont conservés
  au lieu d'être effacés (les accents sont retirés comme avant : ё devient е).
- **Concurrence** : verrous d'approbation, deux scans simultanés, et un scan qui travaille maintenant sur un instantané des règles
  (une correction faite pendant ce temps ne le fait plus échouer).
- **OCR** : budget de temps partagé par page, limite de pixels, texte natif non dupliqué, échecs de Tesseract journalisés,
  Tesseract cherché une seule fois.
- **Modèle local** : texte du document délimité dans le prompt, réponse bornée, signe et fusion des montants corrigés ; une date
  ou un montant que le modèle lit autrement que les règles (quand celles-ci sont sûres) est signalé et noté 0, pour que vous le vérifiiez.
- **Interface** : erreurs traduites, chargements annoncés, historique et recherche sans résultats périmés, confiance donnée
  aussi par un symbole et un mot, contrastes, onglets qui défilent au lieu d'être coupés.
- **Serveur** : `/api` sans slash renvoie du JSON, `index.html` n'est plus mis en cache, secret et cache suivent le bac à sable.

### Pour déployer (rien n'a été fait pour vous)
1. Arrêter le service.
2. `uv run python manage.py migrate` (migrations 0009, 0010, 0011).
3. `cd frontend && npm run build`.
4. Recopier `deploy/docflow-web.service` dans `/etc/systemd/system/` (il pose maintenant `DOCFLOW_HOSTS`, avec les mêmes hôtes
   qu'aujourd'hui), puis `sudo systemctl daemon-reload`. **Obligatoire** : sans `DOCFLOW_HOSTS`, le site ne répond plus qu'à
   `localhost` (le défaut du code ne contient plus le nom ni l'adresse de cette machine).
5. Démarrer le service ; installer le minuteur de sauvegarde si ce n'est pas fait (voir le README).

### À décider (réouvert à la date indiquée ou sur condition)
- Fichiers non PDF, statiques servis par WhiteNoise, horodatages anciens sans fuseau, migrations de schéma : revue le 2026-12-05.

## [0.1.0] - 2026-10-04

Version de départ de l'audit : moteur de classement (OCR local, règles apprises), interface web, recherche plein texte.
