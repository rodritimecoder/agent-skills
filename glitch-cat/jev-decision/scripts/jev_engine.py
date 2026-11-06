#!/usr/bin/env python3
import base64
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import ssl
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

BACKEND_SYSTEMONE = "systemone"
BACKEND_NONE = "none"
EXPECTED_MODEL = "h2o-lightning-4b"
LAST_ERROR: Optional[str] = None

def _concentration(probs: List[float]) -> float:
    k = len(probs)
    if k <= 1:
        return 1.0
    ent = -math.fsum(p * math.log(p) for p in probs if p > 0)
    return min(1.0, max(0.0, 1 - ent / math.log(k)))

class JevEngine:
    def __init__(self, host: Optional[str] = None, port: int = 8083, timeout: float = 5.0):
        env_host = os.environ.get("JEV_HOST")
        env_port = int(os.environ.get("JEV_PORT", os.environ.get("DECISION_PORT", str(port))))
        self.host = host or env_host or "127.0.0.1"
        self.port = port if port != 8083 else env_port
        self.timeout = timeout
        self.scheme = "https" if (".ts.net" in self.host or os.environ.get("JEV_SCHEME") == "https") else "http"
        self.ssl_ctx = ssl.create_default_context()
        self.ssl_ctx.check_hostname = False
        self.ssl_ctx.verify_mode = ssl.CERT_NONE

        self.systemone_url = f"{self.scheme}://{self.host}:{self.port}/v1/systemone"
        self.models_url = f"{self.scheme}://{self.host}:{self.port}/v1/models"
        self.health_url = f"{self.scheme}://{self.host}:{self.port}/health"

        self._systemone_supported: Optional[bool] = None
        self.last_error: Optional[str] = None
        self.model_name: Optional[str] = None

    # ---- backend selection ------------------------------------------------------

    def backend(self) -> str:
        """Return the supported backend only when the H2O model is served."""
        return self._detect_backend()

    def _detect_backend(self) -> str:
        try:
            req = urllib.request.Request(self.models_url)
            ctx = self.ssl_ctx if self.scheme == "https" else None
            with urllib.request.urlopen(req, timeout=3.0, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return BACKEND_NONE
        entries = data.get("data") or []
        if not entries or not isinstance(entries[0], dict):
            return BACKEND_NONE
        entry = entries[0]
        model_id = str(entry.get("id") or "")
        if not model_id:
            return BACKEND_NONE
        if os.environ.get("JEV_REQUIRE_H2O") == "1" and EXPECTED_MODEL not in model_id.lower():
            return BACKEND_NONE
        self.model_name = self.model_name or model_id.rsplit("/", 1)[-1]
        return BACKEND_SYSTEMONE

    def is_online(self) -> bool:
        try:
            req = urllib.request.Request(self.health_url)
            ctx = self.ssl_ctx if self.scheme == "https" else None
            with urllib.request.urlopen(req, timeout=0.8, context=ctx) as resp:
                if resp.status != 200:
                    return False
                self._learn_model_name(resp.read())
                return True
        except Exception:
            return False

    def _learn_model_name(self, body: bytes) -> None:
        """A server that names itself is named in every `source` field."""
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            return
        if isinstance(payload, dict):
            name = payload.get("model") or (payload.get("engine") or {}).get("name")
            if name:
                self.model_name = str(name)

    def source_label(self) -> str:
        return self.model_name or "systemone"

    def _encode_image(self, image: Optional[str]) -> Optional[str]:
        if not image:
            return None
        p = Path(image)
        if p.exists() and p.is_file():
            return base64.b64encode(p.read_bytes()).decode("utf-8")
        if len(image) > 64 and ("/" in image or "+" in image or image.endswith("=")):
            return image
        return None

    def _call_decision(
        self,
        state: str,
        question: str,
        options: Optional[List[str]],
        typ: str,
        image: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """One typed decision through the verified H2O API."""
        if self.backend() != BACKEND_SYSTEMONE:
            return None
        return self._call_systemone(state, question, options, typ, image)

    def _call_systemone(
        self,
        state: str,
        question: str,
        options: Optional[List[str]],
        typ: str,
        image: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """h2o-lightning-4b native /v1/systemone."""
        if self._systemone_supported is False:
            return None
        if not self.is_online():
            return None

        q: Dict[str, Any] = {"type": typ, "instructions": question}
        levels: Optional[List[str]] = None
        if typ == "choice":
            if not options:
                raise ValueError("Options list required for choice primitive")
            q["criteria"] = {str(option): str(option) for option in options}
        elif typ == "score":
            levels = [str(o) for o in (options or ["0.0", "0.25", "0.5", "0.75", "1.0"])]
            q["criteria"] = levels

        payload: Dict[str, Any] = {"state": {"context": state}, "questions": {"answer": q}}
        self._add_image(payload, q, image)

        answers = self._post(payload)
        if answers is None:
            return None
        ans = answers.get("answer")
        if not ans:
            return None
        return self._map_h2o_answer(ans, typ, levels)

    def _add_image(self, payload: Dict[str, Any], question: Dict[str, Any], image: Optional[str]) -> None:
        raw = self._encode_image(image)
        if not raw:
            return
        mime = "image/png"
        if image:
            guess, _ = mimetypes.guess_type(str(image))
            if guess and guess.startswith("image/"):
                mime = guess
        image_format = "jpg" if mime == "image/jpeg" else mime.split("/", 1)[1]
        payload["assets"] = {
            "img": {
                "type": "image",
                "format": image_format,
                "data_base64": raw,
            }
        }
        question["image"] = "img"

    def _map_h2o_answer(self, answer: Dict[str, Any], typ: str,
                        levels: Optional[List[str]]) -> Dict[str, Any]:
        if typ == "noul":
            probs = answer.get("probabilities") or {}
            probability = answer.get("noul", answer.get("probability", probs.get("true")))
            if probability is None:
                probability = 1.0 if answer.get("decision") else 0.0
            return self._map_answer({"noul": float(probability)}, typ, levels)
        if typ == "choice":
            normalized = dict(answer)
            if "choice" not in normalized and "selection" in normalized:
                normalized["choice"] = normalized["selection"]
            return self._map_answer(normalized, typ, levels)
        if "score" in answer:
            probabilities = answer.get("probabilities") or {}
            mapped = self._map_answer({"probabilities": probabilities}, typ, levels) if probabilities else {}
            return {
                "primitive": "score",
                "score": round(min(1.0, max(0.0, float(answer["score"]))), 4),
                "probabilities": mapped.get("probabilities", probabilities),
                "source": self.source_label(),
            }
        return self._map_answer(answer, typ, levels)

    def _post(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """POST one /v1/systemone request. None means "not a decision server".

        The single place the engine talks to the server, so one call and a batch
        cannot drift apart in their error handling.
        """
        if self.backend() != BACKEND_SYSTEMONE or self._systemone_supported is False:
            return None
        if not self.is_online():
            return None
        try:
            req = urllib.request.Request(
                self.systemone_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            ctx = self.ssl_ctx if self.scheme == "https" else None
            with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            global LAST_ERROR
            detail = e.read().decode(errors="replace")[:300]
            if e.code in (404, 501):          # not a decision-model server
                self._systemone_supported = False
                return None
            self._systemone_supported = True
            self.last_error = f"HTTP {e.code} from {self.systemone_url}: {detail}"
            LAST_ERROR = self.last_error
            return None
        except Exception:
            return None

        self._systemone_supported = True
        LAST_ERROR = None
        return data.get("answers") or {}

    def _map_answer(self, ans: Dict[str, Any], typ: str,
                    levels: Optional[List[str]],
                    source: Optional[str] = None) -> Dict[str, Any]:
        """One server answer -> the engine's result shape."""
        source = source or self.source_label()

        if typ == "noul":
            p_true = round(float(ans.get("noul", 0.0)), 4)
            p_false = round(1.0 - p_true, 4)
            return {
                "primitive": "bool",
                "decision": p_true >= 0.5,
                "confidence": round(abs(p_true - 0.5) * 2.0, 4),
                "probabilities": {"true": p_true, "false": p_false},
                "source": source,
            }

        if typ == "score":
            probs_raw = ans.get("probabilities") or {}
            dist: Dict[str, float] = {}
            scalar = 0.0
            labels = levels or []
            numeric = bool(labels)
            for lv in labels:
                try:
                    float(lv)
                except (TypeError, ValueError):
                    numeric = False
                    break
            n = len(labels)
            for k, v in probs_raw.items():
                if not str(k).isdigit():
                    continue
                i = int(k)
                if n and i < n:
                    dist[labels[i]] = round(float(v), 4)
                    if numeric:
                        scalar += float(labels[i]) * float(v)
                    elif n > 1:                      # named levels: expected level index
                        scalar += (i / (n - 1)) * float(v)
                else:
                    dist[str(k)] = round(float(v), 4)
            return {
                "primitive": "score",
                "score": round(min(1.0, max(0.0, scalar)), 4),
                "probabilities": dist or probs_raw,
                "source": source,
            }

        probs = {str(k): round(float(v), 4) for k, v in (ans.get("probabilities") or {}).items()}
        best = ans.get("choice") or (max(probs, key=probs.get) if probs else None)
        conf = ans.get("confidence")
        if conf is None:
            conf = _concentration(list(probs.values())) if probs else 0.0
        return {
            "primitive": "choice",
            "selection": best,
            "confidence": round(float(conf), 4),
            "probabilities": probs,
            "source": source,
        }

    def decide_batch(self, state: str, questions: Dict[str, Dict[str, Any]],
                     image: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """Many typed questions in ONE forward pass.

        ``questions`` maps an id to ``{"type": "bool"|"choice"|"score",
        "instructions": str, "options": [...], "levels": [...]}``. The server
        takes them all at once, so N decisions cost one round trip instead of N.

        Raises ValueError for an unusable question (no options, no levels) rather
        than sending a request the server will reject with a 400.
        """
        built: Dict[str, Any] = {}
        levels_by_id: Dict[str, Optional[List[str]]] = {}
        for qid, spec in questions.items():
            kind = str(spec.get("type", "bool")).lower()
            typ = {"bool": "noul", "noul": "noul", "choice": "choice", "score": "score"}.get(kind)
            if typ is None:
                raise ValueError(
                    f"question {qid!r}: type must be 'bool', 'choice' or 'score' (got {kind!r})"
                )
            q: Dict[str, Any] = {
                "type": typ,
                "instructions": str(spec.get("instructions") or spec.get("question") or ""),
            }
            levels: Optional[List[str]] = None
            if typ == "choice":
                opts = spec.get("options") or []
                if not opts:
                    raise ValueError(f"question {qid!r}: a choice needs a non-empty 'options' list")
                q["criteria"] = {str(o): None for o in opts}
            elif typ == "score":
                levels = [str(x) for x in (spec.get("levels")
                                           or ["0.0", "0.25", "0.5", "0.75", "1.0"])]
                q["criteria"] = levels
            built[qid] = q
            levels_by_id[qid] = levels

        h2o_questions: Dict[str, Dict[str, Any]] = {}
        for qid, spec in built.items():
            question: Dict[str, Any] = {"type": spec["type"], "instructions": spec["instructions"]}
            if spec["type"] == "choice":
                question["criteria"] = {opt: opt for opt in spec["criteria"]}
            elif spec["type"] == "score":
                question["criteria"] = levels_by_id[qid] or []
            h2o_questions[qid] = question

        payload: Dict[str, Any] = {
            "state": {"context": state},
            "questions": h2o_questions,
        }
        if image:
            for question in h2o_questions.values():
                self._add_image(payload, question, image)

        answers = self._post(payload)
        if answers is None:
            raise RuntimeError(
                "the decision server did not answer /v1/systemone — check "
                f"{self.systemone_url.rsplit('/v1/', 1)[0]}/health"
            )
        return {
            qid: self._map_h2o_answer(ans, built[qid]["type"], levels_by_id[qid])
            for qid, ans in answers.items() if qid in built
        }
    def decide_bool(self, context: str, question: str, image: Optional[str] = None) -> Dict[str, Any]:
        res = self._call_decision(context, question, None, "noul", image)
        if res is not None:
            return res

        clean_ctx = context.lower()
        clean_q = question.lower()
        if "supersede" in clean_q or "conflict" in clean_q:
            has_conflict = any(neg in clean_ctx for neg in ["deprecated", "obsolete", "replaced", "instead of", "cancelled", "migrated"])
            p_true = 0.92 if has_conflict else 0.15
        else:
            p_true = 0.50

        return {
            "primitive": "bool",
            "decision": p_true >= 0.5,
            "confidence": round(p_true if p_true >= 0.5 else 1.0 - p_true, 4),
            "probabilities": {"true": round(p_true, 4), "false": round(1.0 - p_true, 4)},
            "source": "heuristic_fallback",
        }

    def decide_choice(self, context: str, question: str, options: List[str], image: Optional[str] = None) -> Dict[str, Any]:
        if not options:
            raise ValueError("Choice primitive requires at least one option")
        res = self._call_decision(context, question, options, "choice", image)
        if res is not None:
            return res

        clean_ctx = set(re.findall(r"[a-zA-Z0-9]+", context.lower()))
        scores = {}
        for opt in options:
            words = set(re.findall(r"[a-zA-Z0-9]+", opt.lower()))
            overlap = sum(1 for w in words if w in clean_ctx)
            scores[opt] = overlap + 0.01

        total = sum(scores.values())
        probs = {k: round(v / total, 4) for k, v in scores.items()}
        best_opt = max(probs.items(), key=lambda x: x[1])

        return {
            "primitive": "choice",
            "selection": best_opt[0],
            "confidence": best_opt[1],
            "probabilities": probs,
            "source": "heuristic_fallback",
        }

    def decide_score(self, context: str, criteria: str, image: Optional[str] = None) -> Dict[str, Any]:
        levels = ["0.0", "0.25", "0.5", "0.75", "1.0"]
        res = self._call_decision(context, criteria, levels, "score", image)
        if res is not None:
            return res

        stop_words = {"and", "or", "the", "a", "an", "for", "with", "in", "to", "of"}
        clean_ctx = set(re.findall(r"[a-zA-Z0-9]+", context.lower()))
        clean_crit = [w for w in re.findall(r"[a-zA-Z0-9]+", criteria.lower()) if w not in stop_words]
        
        match_count = 0
        for w in clean_crit:
            if w in clean_ctx:
                match_count += 1
            elif any(w.startswith(cw[:4]) or cw.startswith(w[:4]) for cw in clean_ctx if len(cw) >= 4 and len(w) >= 4):
                match_count += 1

        score = min(1.0, max(0.0, match_count / max(1, len(clean_crit))))
        return {
            "primitive": "score",
            "score": round(score, 4),
            "source": "heuristic_fallback",
        }

    def decide_composite(
        self,
        context: str,
        question: str,
        options: List[str],
        criteria: Optional[str] = None,
        image: Optional[str] = None
    ) -> Dict[str, Any]:
        gate_res = self.decide_bool(context, question, image=image)
        choice_res = self.decide_choice(context, question, options, image=image)
        score_crit = criteria if criteria else f"Quality and confidence of {choice_res['selection']}"
        score_res = self.decide_score(context, score_crit, image=image)

        return {
            "primitive": "composite",
            "gate": gate_res["decision"],
            "gate_confidence": gate_res["confidence"],
            "action": choice_res["selection"],
            "choice_confidence": choice_res["confidence"],
            "quality_score": score_res["score"],
            "source": gate_res["source"],
        }

    def clean_context_claims(self, claims: List[Dict[str, Any]]) -> Dict[str, Any]:
        sorted_claims = sorted(claims, key=lambda c: c.get("timestamp", ""))
        active_claims = []
        superseded_pairs = []

        for i in range(len(sorted_claims)):
            claim_b = sorted_claims[i]
            is_superseded = False
            for j in range(i + 1, len(sorted_claims)):
                claim_newer = sorted_claims[j]
                ctx = f"Older claim ({claim_b.get('timestamp')}): {claim_b.get('text')}\nNewer claim ({claim_newer.get('timestamp')}): {claim_newer.get('text')}"
                q = "Does the newer claim supersede, negate, or obsolete the older claim?"
                res = self.decide_bool(ctx, q)
                if res["decision"] and res["confidence"] > 0.60:
                    is_superseded = True
                    superseded_pairs.append({
                        "superseded": claim_b,
                        "superseded_by": claim_newer,
                        "confidence": res["confidence"]
                    })
                    break
            if not is_superseded:
                active_claims.append(claim_b)

        return {
            "total_input_claims": len(claims),
            "active_claims_retained": len(active_claims),
            "superseded_count": len(superseded_pairs),
            "active": active_claims,
            "superseded": superseded_pairs,
        }
