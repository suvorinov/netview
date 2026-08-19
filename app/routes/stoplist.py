"""Маршруты Stoplist — управление стоп-листом.

Модуль содержит маршруты для просмотра, добавления и удаления
стоп-слов, используемых для блокировки запросов в Squid.
"""

import logging

from flask import Blueprint, current_app, jsonify, render_template, request

from app.api.logspy_client import LogSpyClient

stoplist_bp = Blueprint("stoplist", __name__)

logger = logging.getLogger(__name__)


def _get_logspy_client() -> LogSpyClient:
    return LogSpyClient(current_app.config["LOGSPY_API_URL"])


@stoplist_bp.route("/")
def index():
    client = _get_logspy_client()
    unavailable_services = []
    try:
        stoplist = client.get_stoplist()
    except Exception as e:
        stoplist = {"words": [], "total": 0, "path": ""}
        logger.error("LogSpy API (stoplist) error: %s", e)
        unavailable_services.append("LogSpy")

    return render_template(
        "stoplist.html",
        stoplist=stoplist,
        unavailable_services=unavailable_services,
    )


@stoplist_bp.route("/add", methods=["POST"])
def add_words():
    client = _get_logspy_client()
    words_text = request.form.get("words", "").strip()
    if not words_text:
        return jsonify({"error": "words required"}), 400

    words = [w.strip() for w in words_text.split("\n") if w.strip()]
    if not words:
        return jsonify({"error": "no valid words"}), 400

    try:
        result = client.add_stoplist_words(words)
        return jsonify(result)
    except Exception as e:
        logger.error("LogSpy API (stoplist add) error: %s", e)
        return jsonify({"error": str(e)}), 500


@stoplist_bp.route("/remove", methods=["POST"])
def remove_word():
    client = _get_logspy_client()
    word = request.form.get("word", "").strip()
    if not word:
        return jsonify({"error": "word required"}), 400

    try:
        result = client.remove_stoplist_word(word)
        return jsonify(result)
    except Exception as e:
        logger.error("LogSpy API (stoplist remove) error: %s", e)
        return jsonify({"error": str(e)}), 500


@stoplist_bp.route("/replace", methods=["POST"])
def replace_all():
    client = _get_logspy_client()
    words_text = request.form.get("words", "").strip()
    if not words_text:
        return jsonify({"error": "words required"}), 400

    words = [w.strip() for w in words_text.split("\n") if w.strip()]
    try:
        result = client.replace_stoplist(words)
        return jsonify(result)
    except Exception as e:
        logger.error("LogSpy API (stoplist replace) error: %s", e)
        return jsonify({"error": str(e)}), 500
