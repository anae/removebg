# removebg

Une application web pour supprimer le fond uni d'une image, ajuster le résultat et télécharger un PNG transparent.

[Voir la démo](https://removebg.ananaba.be) · [Découvrir la Toolbox](https://ananaba.be/applications/)

![Aperçu de removebg](https://ananaba.be/assets/app-removebg.png)

## Fonctionnalités

- premier détourage automatique dès l'import de l'image ;
- ajout par sélection, glisser-déposer ou collage ;
- détection automatique ou sélection manuelle de la couleur de fond ;
- réglage de la tolérance et traitement des zones fermées ;
- aperçu avant/après et téléchargement PNG ;
- validation des formats, dimensions et volumes côté serveur.

## Lancer le projet

```bash
docker compose up -d --build
```

## Stack

FastAPI, Pillow, NumPy, SciPy et une interface HTML/CSS/JavaScript, le tout conteneurisé avec Docker.

Projet conçu par [Elliot Ananaba](https://ananaba.be).
