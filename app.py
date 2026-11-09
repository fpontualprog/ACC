from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from pathlib import Path
from werkzeug.utils import secure_filename
from pypdf import PdfReader
from datetime import datetime
import sqlite3, re, csv, io

BASE=Path(__file__).resolve().parent
UPLOAD=BASE/"uploads"; UPLOAD.mkdir(exist_ok=True)
DB=BASE/"database.sqlite3"
app=Flask(__name__); app.secret_key="chave-local"
RULES=[
("Ensino","Eventos acadêmicos",40,"half","Certificado/declaração com carga horária."),
("Ensino","Disciplinas extras",45,"15","Histórico/declaração de aprovação e ementa."),
("Ensino","Cursos de língua estrangeira",20,"10","Certificado de conclusão com carga horária."),
("Ensino","Educação à distância",30,"ten","Certificado/declaração com carga horária."),
("Ensino","Monitoria",60,"30","Certificado/declaração com carga horária."),
("Ensino","Integração empresa-escola",40,"hour","Contrato/declaração com período, carga horária e descrição."),
("Pesquisa","Participação em projetos de iniciação científica",60,"30","Certificado/declaração com carga horária."),
("Pesquisa","Publicação de trabalhos científicos",45,"publication","Cópia da publicação."),
("Pesquisa","Apresentação de trabalhos científicos",30,"10","Certificado/declaração."),
("Extensão","Projetos de extensão universitária",60,"30","Certificado/declaração com carga horária."),
("Extensão","Atividades de extensão universitária",40,"half","Certificado/declaração com carga horária."),
("Extensão","Organização de eventos de extensão",30,"hour","Certificado/declaração."),
("Extensão","Visitas técnicas",15,"3","Relatório assinado e carimbado."),
("Gestão","Atividades de representação discente",40,"20","Declaração com período, horas e descrição, ratificada pelo DA.")
]
R={x[1]:x for x in RULES}
def conn():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def init():
 with conn() as c:
  c.execute("""CREATE TABLE IF NOT EXISTS ac(id INTEGER PRIMARY KEY,student TEXT,registration TEXT,entry TEXT,filename TEXT,path TEXT,dimension TEXT,modality TEXT,activity_date TEXT,institution TEXT,presented REAL,calculated REAL,status TEXT,note TEXT,extracted TEXT,created TEXT)""")
def required(entry):
 m=re.match(r"(20\d{2})\.([12])$",entry or "")
 if not m:return None
 y,s=map(int,m.groups())
 if 2017<=y<=2021:return 180
 if y>=2022:return 120
 return None
def pdftext(path):
 try:return "\n".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)
 except Exception:return ""
def hours(t):
 for p in [r"(?:carga\s*hor[aá]ria|total\s*de\s*horas|dura[cç][aã]o|CH)\s*[:\-]?\s*(\d+(?:[,.]\d+)?)\s*(?:horas?|h|hs)\b",r"\b(\d+(?:[,.]\d+)?)\s*horas?\b"]:
  m=re.search(p,t,re.I)
  if m:
   try:
    n=float(m.group(1).replace(",",".")); return n if 0<n<2001 else 0
   except:pass
 return 0
def date(t):
 m=re.search(r"\b(\d{1,2})[/. -](\d{1,2})[/. -](20\d{2})\b",t)
 if not m:return ""
 try:return datetime(int(m[3]),int(m[2]),int(m[1])).strftime("%Y-%m-%d")
 except:return ""
def institution(t):
 for line in t.splitlines():
  if re.search(r"universidade|faculdade|instituto|secretaria|prefeitura|empresa",line,re.I):return line.strip()[:150]
 return ""
def modality(t):
 tests=[
 (r"monitoria","Monitoria"),
 (r"inicia[cç][aã]o cient[ií]fica|projeto de pesquisa","Participação em projetos de iniciação científica"),
 (r"resumo simples|resumo expandido|artigo|publica[cç][aã]o","Publicação de trabalhos científicos"),
 (r"apresenta[cç][aã]o de trabalho","Apresentação de trabalhos científicos"),
 (r"projeto de extens[aã]o","Projetos de extensão universitária"),
 (r"atividade de extens[aã]o|a[cç][aã]o de extens[aã]o","Atividades de extensão universitária"),
 (r"visita t[eé]cnica","Visitas técnicas"),
 (r"representa[cç][aã]o discente|centro acad[eê]mico|diret[oó]rio acad[eê]mico","Atividades de representação discente"),
 (r"empresa.?j[uú]nior|est[aá]gio n[aã]o obrigat[oó]rio|trabalho volunt[aá]rio","Integração empresa-escola"),
 (r"curso.*(ingl[eê]s|espanhol|idioma|l[ií]ngua estrangeira)","Cursos de língua estrangeira"),
 (r"ead|educa[cç][aã]o a dist[aâ]ncia|curso on.?line","Educação à distância"),
 (r"disciplina|componente curricular","Disciplinas extras"),
 (r"congresso|semin[aá]rio|simp[oó]sio|palestra|workshop|oficina|minicurso|confer[eê]ncia","Eventos acadêmicos"),
 (r"organiza[cç][aã]o.*evento|comiss[aã]o organizadora","Organização de eventos de extensão")]
 for p,n in tests:
  if re.search(p,t,re.I):return n
 return "Eventos acadêmicos"
def calc(n,h,t):
 rule=R[n]; method=rule[3]
 if method=="half":v=int(h//2)
 elif method=="ten":v=int(h//10)
 elif method=="hour":v=h
 elif method=="publication":
  low=t.lower();v=10 if "resumo simples" in low else 15 if "resumo expandido" in low else 20
 else:v=float(method)
 return min(v,rule[2])
@app.route("/")
def index():
 with conn() as c: rows=c.execute("select * from ac order by id desc").fetchall()
 students=sorted({x["student"] for x in rows})
 student=request.args.get("student") or (students[0] if students else "")
 rs=[x for x in rows if x["student"]==student]
 dims={x:0 for x in ["Ensino","Pesquisa","Extensão","Gestão"]}; valid=pending=0; modes={}
 for a in rs:
  if a["status"]=="Aprovada":
   key=(a["dimension"],a["modality"]); cap=R[a["modality"]][2]
   v=min(a["calculated"],max(0,cap-modes.get(key,0)),max(0,100-dims[a["dimension"]]))
   modes[key]=modes.get(key,0)+v;dims[a["dimension"]]+=v;valid+=v
  else:pending+=a["calculated"]
 entry=rs[0]["entry"] if rs else ""
 need=required(entry); missing=max(0,need-valid) if need else None
 return render_template("index.html",rows=rs,students=students,student=student,dims=dims,valid=valid,pending=pending,need=need,missing=missing,rules=RULES)
@app.post("/upload")
def upload():
 student=request.form.get("student","").strip(); entry=request.form.get("entry","").strip()
 files=request.files.getlist("files")
 if not student or not entry:flash("Informe estudante e período de ingresso.");return redirect(url_for("index"))
 # Garante que a pasta exista mesmo se tiver sido removida após a inicialização.
 UPLOAD.mkdir(parents=True, exist_ok=True)
 count=0
 for f in files:
  if not f.filename:continue
  if Path(f.filename).suffix.lower()!=".pdf":flash("Nesta versão, o envio automático aceita PDF. Imagens podem ser conferidas manualmente.");continue
  name=secure_filename(f.filename); target=UPLOAD/(datetime.now().strftime("%Y%m%d%H%M%S%f")+"_"+name)
  target.parent.mkdir(parents=True, exist_ok=True)
  f.save(target)
  text=pdftext(target); mod=modality(text); h=hours(text); dim=R[mod][0]; calc_h=calc(mod,h,text)
  with conn() as c:c.execute("insert into ac(student,registration,entry,filename,path,dimension,modality,activity_date,institution,presented,calculated,status,note,extracted,created) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
   (student,request.form.get("registration",""),entry,name,str(target),dim,mod,date(text),institution(text),h,calc_h,"Pendente","",text,datetime.now().isoformat()))
  count+=1
 flash(f"{count} certificado(s) importado(s). Revise os dados e o parecer.");return redirect(url_for("index",student=student))
@app.post("/update/<int:i>")
def update(i):
 mod=request.form["modality"];h=float(request.form.get("presented") or 0);t=request.form.get("extracted","")
 with conn() as c:c.execute("update ac set modality=?,dimension=?,activity_date=?,institution=?,presented=?,calculated=?,status=?,note=?,extracted=? where id=?",
 (mod,R[mod][0],request.form.get("activity_date",""),request.form.get("institution",""),h,calc(mod,h,t),request.form.get("status","Pendente"),request.form.get("note",""),t,i))
 flash("Análise salva.");return redirect(url_for("index",student=request.form.get("student","")))
@app.post("/delete/<int:i>")
def delete(i):
 with conn() as c:
  r=c.execute("select path,student from ac where id=?",(i,)).fetchone()
  c.execute("delete from ac where id=?",(i,))
 if r:Path(r["path"]).unlink(missing_ok=True)
 return redirect(url_for("index",student=r["student"] if r else ""))
@app.route("/export")
def export():
 with conn() as c:rs=c.execute("select * from ac").fetchall()
 out=io.StringIO();w=csv.writer(out,delimiter=";");w.writerow(["Estudante","Matrícula","Ingresso","Dimensão","Modalidade","Data","Instituição","Horas certificado","Horas calculadas","Parecer"])
 for a in rs:w.writerow([a["student"],a["registration"],a["entry"],a["dimension"],a["modality"],a["activity_date"],a["institution"],a["presented"],a["calculated"],a["status"]])
 mem=io.BytesIO(("\ufeff"+out.getvalue()).encode("utf-8"));mem.seek(0)
 return send_file(mem,mimetype="text/csv",as_attachment=True,download_name="relatorio_ACs.csv")
if __name__=="__main__":
 init();print("Abra http://127.0.0.1:5000");app.run(host="127.0.0.1",port=5000,debug=False)
