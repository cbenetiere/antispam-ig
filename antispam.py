"""Anti-spam Instagram : masque les commentaires de bots sur les dernières publications.

Aucun appel à une IA. Masquer est réversible (le commentaire reste visible pour son
auteur et peut être réaffiché) ; rien n'est jamais supprimé.

Un commentaire est considéré comme du spam s'il :
- contient au moins `antispam_invisibles_min` caractères invisibles (technique utilisée
  pour déguiser un nom de site et contourner les « Mots masqués » d'Instagram) ;
- ou cite, une fois ces caractères retirés, un domaine de la liste `antispam_domaines`.
"""
import csv
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from zoneinfo import ZoneInfo
FUSEAU = ZoneInfo("Europe/Paris")

GRAPH = "https://graph.facebook.com/v26.0"
INVISIBLES = re.compile("[​-‏⁠-⁤͏﻿­᠎]")
COLONNES = ["date", "heure", "publication", "commentaire_id", "auteur", "texte", "raison", "resultat"]


class ErreurMeta(Exception):
    pass


def texte_clair(texte):
    return INVISIBLES.sub("", texte or "")


def raison_spam(texte, domaines, invisibles_min):
    """Renvoie la raison si c'est du spam, sinon None."""
    n = len(INVISIBLES.findall(texte or ""))
    if n >= invisibles_min:
        return f"{n} caractères invisibles"
    clair = texte_clair(texte).lower()
    for d in domaines:
        if d.lower() in clair:
            return f"domaine {d}"
    return None


class Meta:
    def __init__(self, jeton):
        if not jeton:
            raise ErreurMeta("META_ACCESS_TOKEN manquant dans .env")
        self._jeton = jeton

    def _appel(self, methode, chemin, **params):
        params["access_token"] = self._jeton
        corps = None
        url = f"{GRAPH}/{chemin}"
        if methode == "GET":
            url += "?" + urllib.parse.urlencode(params)
        else:
            corps = urllib.parse.urlencode(params).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=corps, method=methode), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                message = json.load(e).get("error", {}).get("message", "")
            except ValueError:
                message = ""
            raise ErreurMeta(f"HTTP {e.code} : {message.replace(self._jeton, '[MASQUÉ]')[:200]}") from None
        except urllib.error.URLError as e:
            raise ErreurMeta(f"réseau : {e.reason}") from None

    def dernieres_publications(self, ig_user_id, nombre):
        r = self._appel("GET", f"{ig_user_id}/media", fields="id,caption,timestamp", limit=nombre)
        return r.get("data", [])

    def commentaires(self, media_id, maximum=1000):
        """Commentaires visibles et leurs réponses (les commentaires déjà masqués ne reviennent pas)."""
        resultat = []
        r = self._appel("GET", f"{media_id}/comments", limit=100,
                        fields="id,text,username,hidden,replies{id,text,username,hidden}")
        while True:
            for c in r.get("data", []):
                resultat.append(c)
                resultat.extend((c.get("replies") or {}).get("data", []))
            suivant = (r.get("paging") or {}).get("cursors", {}).get("after")
            if not (r.get("paging") or {}).get("next") or len(resultat) >= maximum:
                return resultat
            r = self._appel("GET", f"{media_id}/comments", limit=100, after=suivant,
                            fields="id,text,username,hidden,replies{id,text,username,hidden}")

    def masquer(self, commentaire_id):
        r = self._appel("POST", str(commentaire_id), hide="true")
        if not r.get("success"):
            raise ErreurMeta(f"réponse inattendue : {str(r)[:100]}")


def passer(meta, ig_user_id, reglages, journal_csv, log, maintenant=None):
    """Un passage : lit les dernières publications, masque le spam, note tout dans le CSV."""
    maintenant = maintenant or datetime.now(FUSEAU)
    domaines = reglages["antispam_domaines"]
    invisibles_min = reglages["antispam_invisibles_min"]
    lignes, bilan = [], {"lus": 0, "masques": 0, "echecs": 0}
    for pub in meta.dernieres_publications(ig_user_id, reglages["antispam_publications"]):
        titre = (pub.get("caption") or "").split("\n")[0][:80]
        try:
            commentaires = meta.commentaires(pub["id"])
        except ErreurMeta as e:
            log.error(f"antispam : lecture des commentaires de {pub['id']} : {e}")
            bilan["echecs"] += 1
            continue
        for c in commentaires:
            bilan["lus"] += 1
            if c.get("hidden"):
                continue
            raison = raison_spam(c.get("text"), domaines, invisibles_min)
            if not raison:
                continue
            try:
                meta.masquer(c["id"])
                resultat = "masqué"
                bilan["masques"] += 1
            except ErreurMeta as e:
                resultat = f"échec : {e}"
                bilan["echecs"] += 1
            lignes.append({"date": f"{maintenant:%Y-%m-%d}", "heure": f"{maintenant:%H:%M}", "publication": titre,
                           "commentaire_id": c["id"], "auteur": c.get("username", ""),
                           "texte": texte_clair(c.get("text"))[:200], "raison": raison, "resultat": resultat})
    if lignes and journal_csv is not None:
        nouveau = not journal_csv.exists()
        journal_csv.parent.mkdir(parents=True, exist_ok=True)
        with journal_csv.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLONNES)
            if nouveau:
                w.writeheader()
            w.writerows(lignes)
    log.info(f"antispam : {bilan}")
    return bilan
