"""Un passage anti-spam sur un ou deux comptes Instagram (utilisé par GitHub Actions).

Secrets attendus (jamais écrits dans le code) :
  META_TOKEN_1, IG_USER_ID_1   premier compte
  META_TOKEN_2, IG_USER_ID_2   second compte (facultatif)
Variables facultatives :
  ANTISPAM_DOMAINES   sites de spam, séparés par des virgules
  ANTISPAM_LECTURE_SEULE   « true » : signale sans masquer

Les journaux ne contiennent que des totaux (le dépôt est public) : ni pseudo, ni texte de commentaire.
"""
import logging
import os
import sys

import antispam as asp

PUBLICATIONS = 10        # dernières publications surveillées
INVISIBLES_MIN = 3       # caractères invisibles à partir desquels c'est du spam


class LectureSeule(asp.Meta):
    def masquer(self, commentaire_id):
        return None


def main():
    domaines = [d.strip() for d in os.environ.get("ANTISPAM_DOMAINES", "").split(",") if d.strip()]
    lecture_seule = os.environ.get("ANTISPAM_LECTURE_SEULE", "").lower() == "true"
    reglages = {"antispam_domaines": domaines, "antispam_invisibles_min": INVISIBLES_MIN,
                "antispam_publications": PUBLICATIONS}
    log = logging.getLogger("antispam")
    log.addHandler(logging.NullHandler())
    code, configures = 0, 0
    for n in ("1", "2"):
        jeton, ig = os.environ.get(f"META_TOKEN_{n}", ""), os.environ.get(f"IG_USER_ID_{n}", "")
        if not jeton or not ig:
            print(f"compte {n} : non configuré, ignoré")
            continue
        configures += 1
        try:
            meta = (LectureSeule if lecture_seule else asp.Meta)(jeton)
            bilan = asp.passer(meta, ig, reglages, None, log)
        except asp.ErreurMeta as e:
            print(f"compte {n} : ERREUR {str(e).replace(jeton, '[MASQUÉ]')[:150]}")
            code = 1
            continue
        verbe = "à masquer (lecture seule)" if lecture_seule else "masqué(s)"
        print(f"compte {n} : {bilan['lus']} lu(s), {bilan['masques']} {verbe}, {bilan['echecs']} échec(s)")
    if not configures:
        print("aucun compte configuré")
        return 1
    return code


if __name__ == "__main__":
    sys.exit(main())
