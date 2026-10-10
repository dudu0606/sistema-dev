import os, uuid, time, shutil
import nh3
from datetime import timedelta
from zoneinfo import ZoneInfo
import httpx
from fastapi import FastAPI, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy import select, func, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, joinedload
from .models import (Base, engine, SessionLocal, Usuario, Curso, Aula, LogVisualizacao, Pergunta, now)

SECRET_KEY = os.getenv("SECRET_KEY", "dev-troque-em-producao")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
app = FastAPI(title="Beit")
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

def embed(url: str):
    u = url or ""
    vid = None
    if "youtube.com/watch" in u: vid = u.split("v=")[1].split("&")[0]
    elif "youtu.be/" in u: vid = u.split("youtu.be/")[1].split("?")[0]
    elif "youtube.com/live/" in u: vid = u.split("/live/")[1].split("?")[0]
    if vid: return {"kind": "iframe", "src": f"https://www.youtube.com/embed/{vid}"}
    if u.startswith("/uploads/") or u.lower().endswith((".mp4", ".webm")):
        return {"kind": "video", "src": u}
    return {"kind": "iframe", "src": u}
templates.env.globals["embed"] = embed

def endereco(u):
    rua = (u.rua or "") + (f", {u.numero}" if u.numero else "")
    partes = [x for x in (rua, u.bairro, f"{u.cidade}/{u.uf}") if x]
    return " - ".join(partes)
templates.env.globals["endereco"] = endereco

def hora(dt, fmt="%d/%m/%Y %H:%M"):
    """Mostra datas no horario de Brasilia."""
    return dt.astimezone(ZoneInfo("America/Sao_Paulo")).strftime(fmt) if dt else ""
templates.env.filters["hora"] = hora

TAGS = {"p","br","strong","b","em","i","u","s","h1","h2","h3","h4","ul","ol","li","blockquote",
        "pre","code","a","span","div","hr","sub","sup","table","thead","tbody","tr","th","td"}
ESTILOS = {"color","background-color","font-size","font-family","font-weight","font-style","text-align","text-decoration"}
def limpar_html(h: str) -> str:
    h = nh3.clean(h or "", tags=TAGS,
                  attributes={"*": {"class", "style"}, "a": {"href", "target"}},
                  filter_style_properties=ESTILOS, url_schemes={"http", "https", "mailto"},
                  link_rel="noopener noreferrer")
    return "" if nh3.clean(h, tags=set()).strip() == "" else h

@app.on_event("startup")
def startup():
    for _ in range(30):  # espera o Postgres subir
        try:
            Base.metadata.create_all(engine); break
        except OperationalError:
            time.sleep(2)
    with engine.begin() as c:  # migracao leve: colunas novas em bancos ja existentes
        for sql in ("ALTER TABLE aulas ADD COLUMN IF NOT EXISTS conteudo TEXT DEFAULT ''",
                    "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS rua VARCHAR(160)",
                    "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS numero VARCHAR(20)",
                    "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS bairro VARCHAR(100)"):
            c.execute(text(sql))
    with SessionLocal() as db:
        email = os.getenv("ADMIN_EMAIL", "admin@sistema.dev")
        if not db.scalar(select(Usuario).where(Usuario.email == email)):
            db.add(Usuario(nome="Administrador", email=email, cidade="Rio de Janeiro", uf="RJ",
                           latitude=-22.9068, longitude=-43.1729, perfil="admin",
                           senha_hash=pwd.hash(os.getenv("ADMIN_PASSWORD", "admin123"))))
        if not db.scalar(select(Curso)):
            db.add(Curso(titulo="Geral", descricao="Curso padrao"))
        db.commit()

def get_db():
    with SessionLocal() as db:
        yield db

def current_user(request: Request, db: Session = Depends(get_db)):
    t = request.cookies.get("token")
    if not t: return None
    try:
        uid = jwt.decode(t, SECRET_KEY, algorithms=["HS256"])["sub"]
        return db.get(Usuario, uuid.UUID(uid))
    except (JWTError, ValueError, KeyError):
        return None

def need(*perfis):
    def dep(user=Depends(current_user)):
        if not user: raise HTTPException(status_code=303, headers={"Location": "/login"})
        if perfis and user.perfil not in perfis: raise HTTPException(403, "Sem permissao")
        return user
    return dep

def render(request, name, user, **ctx):
    avisos = 0  # bolinha no menu: respostas novas (aluno) ou perguntas pendentes (pastor/admin)
    if user:
        with SessionLocal() as db:
            if user.perfil in ("professor", "admin"):
                avisos = db.scalar(select(func.count(Pergunta.id)).where(Pergunta.resposta.is_(None))) or 0
            else:
                avisos = db.scalar(select(func.count(Pergunta.id)).where(
                    Pergunta.usuario_id == user.id, Pergunta.resposta.is_not(None), Pergunta.visto == False)) or 0  # noqa: E712
    return templates.TemplateResponse(request, name, {"user": user, "avisos": avisos, **ctx})

def geocode(cidade, uf, bairro="", rua="", numero=""):
    """Tenta rua -> bairro -> cidade (mais preciso primeiro)."""
    tentativas = []
    if rua:
        tentativas.append({"street": f"{numero} {rua}".strip(), "city": cidade, "state": uf, "country": "Brazil"})
    if bairro:
        tentativas.append({"q": f"{bairro}, {cidade}, {uf}, Brasil"})
    tentativas.append({"city": cidade, "state": uf, "country": "Brazil"})
    for i, params in enumerate(tentativas):
        try:
            if i: time.sleep(1)  # politica do Nominatim: 1 req/s
            r = httpx.get("https://nominatim.openstreetmap.org/search", timeout=6,
                          params={**params, "format": "json", "limit": 1},
                          headers={"User-Agent": "beit/1.0"})
            d = r.json()
            if d: return float(d[0]["lat"]), float(d[0]["lon"])
        except Exception:
            pass
    return None, None

# ---------- Auth ----------
@app.get("/")
def home(user=Depends(current_user)):
    return RedirectResponse("/portal" if user else "/login")

@app.get("/login")
def login_page(request: Request, user=Depends(current_user)):
    return render(request, "login.html", user, erro=None)

@app.post("/login")
def login(request: Request, email: str = Form(...), senha: str = Form(...), db: Session = Depends(get_db)):
    u = db.scalar(select(Usuario).where(Usuario.email == email.lower().strip()))
    if not u or not pwd.verify(senha, u.senha_hash):
        return render(request, "login.html", None, erro="E-mail ou senha invalidos")
    token = jwt.encode({"sub": str(u.id), "exp": now() + timedelta(hours=12)}, SECRET_KEY, algorithm="HS256")
    dest = {"admin": "/admin", "professor": "/professor"}.get(u.perfil, "/portal")
    r = RedirectResponse(dest, status_code=303)
    r.set_cookie("token", token, httponly=True, samesite="lax", secure=os.getenv("COOKIE_SECURE", "1") == "1", max_age=43200)
    return r

@app.get("/cadastrar")
def cad_page(request: Request, user=Depends(current_user)):
    return render(request, "cadastro.html", user, erro=None)

@app.post("/cadastrar")
def cadastrar(request: Request, nome: str = Form(...), email: str = Form(...), senha: str = Form(...),
              rua: str = Form(...), numero: str = Form(""), bairro: str = Form(...),
              cidade: str = Form(...), uf: str = Form(...), db: Session = Depends(get_db)):
    email = email.lower().strip()
    if len(senha) < 6 or db.scalar(select(Usuario).where(Usuario.email == email)):
        return render(request, "cadastro.html", None, erro="E-mail ja cadastrado ou senha curta (min. 6)")
    lat, lng = geocode(cidade.strip(), uf.strip().upper(), bairro.strip(), rua.strip(), numero.strip())
    db.add(Usuario(nome=nome.strip(), email=email, senha_hash=pwd.hash(senha), cidade=cidade.strip(),
                   uf=uf.strip().upper()[:2], rua=rua.strip(), numero=numero.strip() or None,
                   bairro=bairro.strip(), latitude=lat, longitude=lng))
    db.commit()
    return RedirectResponse("/login", status_code=303)

@app.get("/perfil")
def perfil_page(request: Request, user=Depends(need())):
    return render(request, "perfil.html", user, u=user, ok=False)

@app.post("/perfil")
def perfil_save(request: Request, user=Depends(need()), db: Session = Depends(get_db),
                rua: str = Form(...), numero: str = Form(""), bairro: str = Form(...),
                cidade: str = Form(...), uf: str = Form(...)):
    u = db.get(Usuario, user.id)
    u.rua, u.numero, u.bairro = rua.strip(), numero.strip() or None, bairro.strip()
    u.cidade, u.uf = cidade.strip(), uf.strip().upper()[:2]
    u.latitude, u.longitude = geocode(u.cidade, u.uf, u.bairro, u.rua, u.numero or "")
    db.commit()
    return render(request, "perfil.html", u, u=u, ok=True)

@app.get("/sair")
def sair():
    r = RedirectResponse("/login"); r.delete_cookie("token"); return r

# ---------- Portal do aluno ----------
@app.get("/portal")
def portal(request: Request, user=Depends(need()), db: Session = Depends(get_db)):
    aulas = db.scalars(select(Aula).options(joinedload(Aula.curso)).where(Aula.ativa == True)
                       .order_by(Aula.criada_em.desc())).all()
    return render(request, "portal.html", user, aulas=aulas)

@app.get("/aula/{aula_id}")
def ver_aula(aula_id: uuid.UUID, request: Request, user=Depends(need()), db: Session = Depends(get_db)):
    a = db.get(Aula, aula_id)
    if not a or not a.ativa: raise HTTPException(404)
    perguntas = db.scalars(select(Pergunta).where(Pergunta.aula_id == a.id, Pergunta.usuario_id == user.id)
                           .order_by(Pergunta.criada_em.desc())).all()
    resp = render(request, "aula.html", user, aula=a, perguntas=perguntas)
    for p in perguntas:  # o aluno esta vendo a resposta agora
        if p.resposta and not p.visto: p.visto = True
    db.commit()
    return resp

# ---------- Perguntas ao pastor (assincrono) ----------
@app.post("/aula/{aula_id}/pergunta")
def perguntar(aula_id: uuid.UUID, user=Depends(need()), db: Session = Depends(get_db), texto: str = Form(...)):
    a = db.get(Aula, aula_id)
    if not a or not a.ativa: raise HTTPException(404)
    texto = texto.strip()
    if not texto: raise HTTPException(400, "Escreva sua pergunta")
    db.add(Pergunta(usuario_id=user.id, aula_id=aula_id, texto=texto[:2000])); db.commit()
    return RedirectResponse(f"/aula/{aula_id}?enviada=1#perguntas", status_code=303)

@app.get("/minhas-perguntas")
def minhas_perguntas(request: Request, user=Depends(need()), db: Session = Depends(get_db)):
    perguntas = db.scalars(select(Pergunta).options(joinedload(Pergunta.aula), joinedload(Pergunta.respondida_por))
                           .where(Pergunta.usuario_id == user.id).order_by(Pergunta.criada_em.desc())).all()
    resp = render(request, "minhas_perguntas.html", user, perguntas=perguntas)
    for p in perguntas:
        if p.resposta and not p.visto: p.visto = True
    db.commit()
    return resp

@app.post("/api/v1/aulas/{aula_id}/play")
def play(aula_id: uuid.UUID, user=Depends(need()), db: Session = Depends(get_db)):
    if not db.get(Aula, aula_id): raise HTTPException(404)
    db.add(LogVisualizacao(usuario_id=user.id, aula_id=aula_id)); db.commit()
    return {"ok": True}

# ---------- Professor / Pastor ----------
@app.get("/professor")
def professor(request: Request, user=Depends(need("professor", "admin")), db: Session = Depends(get_db)):
    cursos = db.scalars(select(Curso).where(Curso.ativo == True)).all()
    aulas = db.scalars(select(Aula).options(joinedload(Aula.curso)).order_by(Aula.criada_em.desc())).all()
    total = db.scalar(select(func.count(LogVisualizacao.id)))
    unicos = db.scalar(select(func.count(func.distinct(LogVisualizacao.usuario_id))))
    recentes = db.scalars(select(LogVisualizacao).options(joinedload(LogVisualizacao.usuario), joinedload(LogVisualizacao.aula))
                          .order_by(LogVisualizacao.acessado_em.desc()).limit(50)).all()
    perguntas = db.scalars(select(Pergunta).options(joinedload(Pergunta.usuario), joinedload(Pergunta.aula), joinedload(Pergunta.respondida_por))
                           .order_by(Pergunta.criada_em.desc()).limit(200)).all()
    pendentes = [p for p in perguntas if not p.resposta]
    respondidas = [p for p in perguntas if p.resposta]
    return render(request, "professor.html", user, cursos=cursos, aulas=aulas, total=total, unicos=unicos,
                  recentes=recentes, pendentes=pendentes, respondidas=respondidas[:30])

@app.post("/professor/pergunta/{pid}/responder")
def responder(pid: uuid.UUID, user=Depends(need("professor", "admin")), db: Session = Depends(get_db), resposta: str = Form(...)):
    p = db.get(Pergunta, pid)
    if not p: raise HTTPException(404)
    resposta = resposta.strip()
    if not resposta: raise HTTPException(400, "Escreva a resposta")
    p.resposta, p.respondida_por_id, p.respondida_em, p.visto = resposta[:4000], user.id, now(), False
    db.commit()
    return RedirectResponse("/professor#perguntas", status_code=303)

@app.post("/professor/aula")
def criar_aula(user=Depends(need("professor", "admin")), db: Session = Depends(get_db),
               titulo: str = Form(...), descricao: str = Form(""), conteudo: str = Form(""), curso_id: uuid.UUID = Form(...),
               tipo: str = Form("aula"), video_url: str = Form(""), arquivo: UploadFile | None = File(None)):
    url = video_url.strip()
    if arquivo and arquivo.filename:
        ext = os.path.splitext(arquivo.filename)[1].lower()
        if ext not in (".mp4", ".webm"): raise HTTPException(400, "Envie .mp4 ou .webm")
        nome = f"{uuid.uuid4().hex}{ext}"
        with open(os.path.join(UPLOAD_DIR, nome), "wb") as f: shutil.copyfileobj(arquivo.file, f)
        url = f"/uploads/{nome}"
    if not url: raise HTTPException(400, "Informe um link ou envie um arquivo")
    db.add(Aula(titulo=titulo, descricao=descricao, conteudo=limpar_html(conteudo), curso_id=curso_id, tipo=tipo, video_url=url)); db.commit()
    return RedirectResponse("/professor", status_code=303)

@app.post("/professor/aula/{aula_id}/toggle")
def toggle(aula_id: uuid.UUID, user=Depends(need("professor", "admin")), db: Session = Depends(get_db)):
    a = db.get(Aula, aula_id); a.ativa = not a.ativa; db.commit()
    return RedirectResponse("/professor", status_code=303)

@app.get("/api/v1/admin/mapa")
def mapa(user=Depends(need("professor", "admin")), db: Session = Depends(get_db)):
    """Uma entrada por pessoa que acessou: nome, local e quantidade de acessos."""
    q = (select(Usuario, func.count(LogVisualizacao.id), func.max(LogVisualizacao.acessado_em))
         .join(LogVisualizacao, LogVisualizacao.usuario_id == Usuario.id)
         .where(Usuario.latitude.is_not(None))
         .group_by(Usuario.id))
    return [{"nome": u.nome, "local": endereco(u), "bairro": u.bairro, "cidade": u.cidade, "uf": u.uf,
             "lat": u.latitude, "lng": u.longitude, "acessos": n,
             "ultimo": ultimo.astimezone(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m %H:%M") if ultimo else ""}
            for u, n, ultimo in db.execute(q)]

# ---------- Admin (cursos e usuarios) ----------
@app.get("/admin")
def admin(request: Request, user=Depends(need("admin")), db: Session = Depends(get_db)):
    return render(request, "admin.html", user, cursos=db.scalars(select(Curso)).all(),
                  usuarios=db.scalars(select(Usuario).order_by(Usuario.nome)).all())

@app.post("/admin/curso")
def novo_curso(user=Depends(need("admin")), db: Session = Depends(get_db), titulo: str = Form(...), descricao: str = Form("")):
    db.add(Curso(titulo=titulo, descricao=descricao)); db.commit()
    return RedirectResponse("/admin", status_code=303)

@app.post("/admin/curso/{cid}/toggle")
def toggle_curso(cid: uuid.UUID, user=Depends(need("admin")), db: Session = Depends(get_db)):
    c = db.get(Curso, cid); c.ativo = not c.ativo; db.commit()
    return RedirectResponse("/admin", status_code=303)

@app.post("/admin/usuario/{uid}/perfil")
def set_perfil(uid: uuid.UUID, perfil: str = Form(...), user=Depends(need("admin")), db: Session = Depends(get_db)):
    if perfil not in ("aluno", "professor", "admin"): raise HTTPException(400)
    u = db.get(Usuario, uid); u.perfil = perfil; db.commit()
    return RedirectResponse("/admin", status_code=303)

@app.get("/healthz")
def health(): return {"status": "ok"}
