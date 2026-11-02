"""
PRISM-EDU Dashboard -- Gerenciamento do servidor OpenCode.
Extraido de app.py para modularizacao.
"""
import streamlit as st
import time
import subprocess
import os
import logging
import requests
import base64
import atexit
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config import RAIZ_PROJETO, MODELOS_OPENCODE


OPENCODE_SERVER_URL = "http://localhost:4096"
OPENCODE_USERNAME = "opencode"


def _get_logger():
    logger = logging.getLogger("opencode_integration")
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


logger = _get_logger()


def _senha_efetiva():
    return st.session_state.get("senha_opencode", "").strip()


def _auth_headers():
    senha = _senha_efetiva()
    if senha:
        credentials = f"{OPENCODE_USERNAME}:{senha}"
        encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
        return {"Authorization": f"Basic {encoded}"}
    return {}


def servidor_opencode_ativo():
    try:
        resp = requests.get(f"{OPENCODE_SERVER_URL}/global/health", timeout=3)
        if resp.status_code == 200:
            return True
    except Exception:
        pass
    headers = _auth_headers()
    if headers:
        try:
            resp = requests.get(f"{OPENCODE_SERVER_URL}/global/health", headers=headers, timeout=3)
            return resp.status_code == 200
        except Exception:
            pass
    return False


def _check_zen_rate_limit():
    try:
        headers = _auth_headers()
        status_resp = requests.get(f"{OPENCODE_SERVER_URL}/session/status", headers=headers, timeout=10)
        if status_resp.status_code == 200:
            status_data = status_resp.json()
            for session_id, info in status_data.items():
                if isinstance(info, dict) and info.get("type") == "retry":
                    msg = info.get("message", "")
                    next_ts = info.get("next", 0)
                    if "Free usage exceeded" in msg or "rate limit" in msg.lower():
                        reset_time = None
                        if next_ts:
                            reset_time = time.strftime("%H:%M:%S", time.localtime(next_ts / 1000))
                        return {"limited": True, "message": msg, "reset_at": reset_time, "next_timestamp": next_ts}
        return {"limited": False}
    except Exception:
        return {"limited": False}


def procurar_opencode():
    try:
        result = subprocess.run(["opencode", "--version"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return "opencode"
    except Exception:
        pass
    for name in ["opencode-cli.exe", "opencode.exe", "opencode.cmd"]:
        try:
            result = subprocess.run(["where", name], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return result.stdout.strip().split("\n")[0].strip()
        except Exception:
            pass
    localappdata = os.environ.get("LOCALAPPDATA", "")
    candidatos = [
        Path(localappdata) / "opencode" / "opencode-cli.exe",
        Path(localappdata) / "opencode" / "opencode.exe",
        RAIZ_PROJETO / "opencode.exe",
    ]
    for c in candidatos:
        if c.exists():
            return str(c)
    return None


def iniciar_servidor_opencode():
    if servidor_opencode_ativo():
        return True
    exe = procurar_opencode()
    if not exe:
        return False
    try:
        cmd = [exe, "serve", "--port", "4096"]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(RAIZ_PROJETO))
        st.session_state.opencode_server_proc = proc
        for _ in range(15):
            if servidor_opencode_ativo():
                return True
            time.sleep(1)
        proc.kill()
        return False
    except Exception as e:
        logger.error(f"Erro ao iniciar servidor OpenCode: {e}")
        return False


def _parar_servidor_opencode():
    proc = st.session_state.get("opencode_server_proc")
    if proc and proc.poll() is None:
        try:
            proc.kill()
        except Exception:
            pass


atexit.register(_parar_servidor_opencode)


def enviar_prompt_opencode(prompt, model_id="big-pickle", timeout=300):
    if not servidor_opencode_ativo():
        return {"success": False, "response": "", "error": "Servidor OpenCode nao esta ativo.", "model": model_id}
    url = f"{OPENCODE_SERVER_URL}/session"
    headers = _auth_headers()
    headers["Content-Type"] = "application/json"
    try:
        session_resp = requests.post(url, json={"message": "Analise de dados ENADE"}, headers=headers, timeout=15)
        if session_resp.status_code != 200:
            return {"success": False, "response": "", "error": f"Falha ao criar sessao: HTTP {session_resp.status_code}", "model": model_id}
        session_data = session_resp.json()
        session_id = session_data.get("id")
        if not session_id:
            return {"success": False, "response": "", "error": "Sessao criada sem ID valido.", "model": model_id}
        msg_url = f"{OPENCODE_SERVER_URL}/session/{session_id}/prompt_async"
        msg_body = {"parts": [{"type": "text", "text": prompt}], "model": {"providerID": "opencode", "modelID": model_id}}
        async_resp = requests.post(msg_url, json=msg_body, headers=headers, timeout=30)
        if async_resp.status_code != 204:
            return {"success": False, "response": "", "error": f"Falha ao enviar mensagem: HTTP {async_resp.status_code}", "model": model_id}
        start_time = time.time()
        while time.time() - start_time < timeout:
            time.sleep(3)
            status_resp = requests.get(f"{OPENCODE_SERVER_URL}/session/status", headers=headers, timeout=10)
            if status_resp.status_code == 200:
                status_data = status_resp.json()
                current_status = status_data.get(session_id, {})
                if current_status.get("type") == "retry":
                    error_msg = current_status.get("message", "")
                    if "Free usage exceeded" in error_msg or "rate limit" in error_msg.lower():
                        next_ts = current_status.get("next", 0)
                        reset_time = time.strftime("%H:%M:%S", time.localtime(next_ts / 1000)) if next_ts else "desconhecido"
                        return {"success": False, "response": "", "error": f"Limite de uso gratuito excedido. Reset as {reset_time}.", "model": model_id, "rate_limit_info": {"limited": True, "reset_at": reset_time}}
            msg_list_resp = requests.get(f"{OPENCODE_SERVER_URL}/session/{session_id}/message?limit=5", headers=headers, timeout=10)
            if msg_list_resp.status_code != 200:
                continue
            messages = msg_list_resp.json()
            if not isinstance(messages, list):
                continue
            for msg in messages:
                info = msg.get("info", {})
                if info.get("role") == "assistant":
                    for part in msg.get("parts", []):
                        if part.get("type") == "text":
                            text = part.get("text", "")
                            if text and len(text.strip()) > 10:
                                elapsed = int(time.time() - start_time)
                                return {"success": True, "response": text, "error": "", "model": model_id, "elapsed": elapsed}
        return {"success": False, "response": "", "error": f"Timeout apos {timeout}s.", "model": model_id}
    except requests.exceptions.ConnectionError as e:
        return {"success": False, "response": "", "error": f"Erro de conexao: {str(e)}", "model": model_id}
    except Exception as e:
        return {"success": False, "response": "", "error": f"Erro: {str(e)}", "model": model_id}
