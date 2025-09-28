import os
import random
import pathlib
from datetime import datetime
from functools import wraps
import requests
from flask import (Flask, flash, redirect, render_template, request, session,
                   url_for, jsonify, send_from_directory)
from flask_mail import Mail, Message
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from supabase import create_client, Client
import midtransclient
import base64

# ---------- CONFIG ----------
BASE_DIR = pathlib.Path(__file__).parent.resolve()
UPLOAD_FOLDER = BASE_DIR / "static" / "images"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

# Create upload folder if missing
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.secret_key = "supersecret_change_this"
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)

# Mail config (ganti sesuai akun SMTP Anda)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'idlaceup@gmail.com'
app.config['MAIL_PASSWORD'] = 'rdrw lxyh jlze xumf'
app.config['MAIL_DEFAULT_SENDER'] = app.config['MAIL_USERNAME']

mail = Mail(app)

# ---------- SUPABASE ----------
url = "https://gnhgcpdfnrrepdlarjuh.supabase.co"
key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImduaGdjcGRmbnJyZXBkbGFyanVoIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTczMTUyMDYsImV4cCI6MjA3Mjg5MTIwNn0.wbcp3WLpeVeMHC1iSoLeQY9ZrgdNXY-cbv4PF1ZdMRA"
supabase: Client = create_client(url, key)

# ---------- UTILITIES ----------
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Silakan login terlebih dahulu.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get('role') != 'admin':
            flash("Akses admin diperlukan.", "danger")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper

def fetch_one(query):
    """Execute a supabase query builder and return single row dict or None."""
    res = query.execute()
    return res.data[0] if res.data else None

def fetch_all(query):
    """Execute a supabase query builder and return list (maybe empty)."""
    return query.execute().data

# ---------- CONSTANTS / EXTERNAL APIs ----------
RAJAONGKIR_API_KEY = "of3SPrp00bb871131e3f0934hWkaRJja"
BASE_URL = "https://rajaongkir.komerce.id/api/v1"

# ---------- CONFIG ORIGIN ----------
ORIGIN_PROVINCE_ID = 11
ORIGIN_CITY_ID = 256
ORIGIN_CITY_NAME = "Kota Malang"
ORIGIN_POSTAL_CODE = "65112"
ORIGIN_SUBDISTRICT_ID = 3635  # Kedungkandang


def get_provinces():
    data = supabase.table("tb_ro_provinces").select("province_id, province_name").execute()
    rows = data.data or []
    return [{"label": r["province_name"], "value": r["province_id"]} for r in rows]

def get_cities(province_id):
    if not province_id:
        return []
    data = supabase.table("tb_ro_cities").select("city_id, city_name").eq("province_id", province_id).execute()
    rows = data.data or []
    return [{"label": r["city_name"], "value": r["city_id"]} for r in rows]

def get_subdistricts(city_id):
    if not city_id:
        return []
    data = supabase.table("tb_ro_subdistricts").select("subdistrict_id, subdistrict_name").eq("city_id", city_id).execute()
    rows = data.data or []
    return [{"label": r["subdistrict_name"], "value": r["subdistrict_id"]} for r in rows]

def get_name(table, key_col, name_col, key_val):
    if not key_val:
        return "-"
    data = supabase.table(table).select(name_col).eq(key_col, key_val).limit(1).execute()
    if data.data:
        return data.data[0][name_col]
    return "-"

# --- Midtrans Setup ---
snap = midtransclient.Snap(
    is_production=False,
    server_key='Mid-server-7j3y9yQxFicv3QvKQVc8_Ebl'
)

MIDTRANS_SERVER_KEY = "Mid-server-7j3y9yQxFicv3QvKQVc8_Ebl"
MIDTRANS_SERVER_KEY_BASE64 = base64.b64encode(f"{MIDTRANS_SERVER_KEY}:".encode()).decode()

def create_transaction(order_id, gross_amount, items, ongkir=0):
    # siapkan item_details untuk Midtrans
    item_details = []
    for item in items:
        item_details.append({
            "id": str(item["id"]),          # ✅ ID produk
            "price": int(item["price"]),    # ✅ harga
            "quantity": int(item["quantity"]),  # ✅ jumlah
            "name": item["name"][:50]       # ✅ nama produk
        })

    # tambahkan ongkir
    if ongkir > 0:
        item_details.append({
            "id": "ONGKIR",
            "price": int(ongkir),
            "quantity": 1,
            "name": "Ongkos Kirim"
        })

    payload = {
        "transaction_details": {
            "order_id": str(order_id),
            "gross_amount": int(gross_amount),
        },
        "item_details": item_details,
        "credit_card": {
            "secure": True
        }
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {MIDTRANS_SERVER_KEY_BASE64}"
    }

    resp = requests.post(
        "https://app.sandbox.midtrans.com/snap/v1/transactions",
        headers=headers,
        json=payload
    )
    resp.raise_for_status()
    return resp.json()

# ---------- ROUTES ----------
@app.route("/")
def index():
    search = request.args.get("search", "")
    tag = request.args.get("tag", "")
    brand = request.args.get("brand", "")
    harga_min = request.args.get("harga_min", "")
    harga_max = request.args.get("harga_max", "")

    query = supabase.table("products").select("*")
    if search:
        query = query.ilike("nama", f"%{search}%")
    if tag:
        query = query.eq("tag", tag)
    if brand:
        query = query.eq("brand", brand)
    if harga_min:
        # store numeric filter as int/float if needed
        query = query.gte("harga", int(harga_min) if harga_min.isdigit() else harga_min)
    if harga_max:
        query = query.lte("harga", int(harga_max) if harga_max.isdigit() else harga_max)

    products = fetch_all(query)
    return render_template("index.html", products=products,
                           search=search, tag=tag, brand=brand,
                           harga_min=harga_min, harga_max=harga_max)

@app.route("/products")
def products():
    search = request.args.get("search", "")
    tag = request.args.get("tag", "")
    brand = request.args.get("brand", "")
    min_price = request.args.get("min_price", "")
    max_price = request.args.get("max_price", "")
    sort = request.args.get("sort", "")

    query = supabase.table("products").select("id,nama,harga,gambar,rating,stok,deskripsi,tag,brand")
    if search:
        query = query.ilike("nama", f"%{search}%")
    if tag:
        query = query.eq("tag", tag)
    if brand:
        query = query.eq("brand", brand)
    if min_price:
        query = query.gte("harga", int(min_price) if min_price.isdigit() else min_price)
    if max_price:
        query = query.lte("harga", int(max_price) if max_price.isdigit() else max_price)

    if sort == "cheap":
        query = query.order("harga", desc=False)
    elif sort == "expensive":
        query = query.order("harga", desc=True)
    else:
        query = query.order("id", desc=True)

    products = fetch_all(query)

    #ambil nilai unik untuk dropdown brand & tag
    tags = fetch_all(supabase.table("products").select("tag").not_.is_("tag", None).execute())
    brands = fetch_all(supabase.table("products").select("brand").not_.is_("brand", None).execute())

    unique_tags = sorted(set([row["tag"] for row in tags if row.get("tag")]))
    unique_brands = sorted(set([row["brand"] for row in brands if row.get("brand")]))

    return render_template(
        "product.html",
        products=products,
        tags=unique_tags,
        brands=unique_brands
    )

@app.route("/product/<int:produk_id>")
def product_detail(produk_id):
    product = fetch_one(supabase.table("products").select("*").eq("id", produk_id))
    if not product:
        flash("Produk tidak ditemukan.", "danger")
        return redirect(url_for("index"))

    other_products = fetch_all(
        supabase.table("products").select("*").neq("id", produk_id).limit(4)
    )
    return render_template("product_detail.html", product=product, other_products=other_products)

# ---------------- Authentication ----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or not password:
            flash("Lengkapi semua field.", "warning")
            return redirect(url_for("register"))

        existing = fetch_one(supabase.table("users").select("id").eq("email", email))
        if existing:
            flash("Email sudah terdaftar. Silakan login.", "warning")
            return redirect(url_for("login"))

        otp = str(random.randint(100000, 999999))
        session['reg_otp'] = otp
        session['reg_temp_user'] = {
            "name": name,
            "email": email,
            "password_hash": generate_password_hash(password)
        }

        try:
            msg = Message("Mau Wangi - Kode OTP Anda", recipients=[email])
            # preserve original HTML email template
            msg.html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    background-color: #fdf8f5;
                }}
                .container {{
                    max-width: 600px;
                    margin: 20px auto;
                    background: #ffffff;
                    border-radius: 12px;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
                    padding: 30px;
                    text-align: center;
                }}
                h2 {{
                    color: #5c4033;
                }}
                p {{
                    color: #333333;
                    font-size: 16px;
                    line-height: 1.5;
                }}
                .otp {{
                    display: block;
                    font-size: 28px;
                    font-weight: bold;
                    color: #a67b5b;
                    margin: 20px 0;
                }}
                .footer {{
                    text-align: center;
                    font-size: 13px;
                    color: #777;
                    margin-top: 30px;
                }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h2>✨ Mau Wangi ✨</h2>
                    <p>Halo {name},</p>
                    <p>Terima kasih telah mendaftar di <b>Mau Wangi</b>, destinasi parfum eksklusif pilihan Anda.  
                    Untuk melanjutkan registrasi, silakan gunakan kode OTP berikut:</p>
                    <span class="otp">{otp}</span>
                    <p>Kode ini hanya berlaku selama beberapa menit.  
                    Jangan bagikan kode ini kepada siapa pun untuk menjaga keamanan akun Anda.</p>
                    <div class="footer">
                        <p>Wangi yang menyempurnakan hari Anda 🌸</p>
                        <p>&copy; 2025 Mau Wangi. All rights reserved.</p>
                    </div>
                </div>
            </body>
            </html>
            """
            mail.send(msg)
            flash("Kode OTP dikirim ke email Anda. Periksa kotak masuk.", "info")
            return redirect(url_for("verify"))
        except Exception as e:
            # fallback: insert user directly if SMTP fails (local dev)
            supabase.table("users").insert({
                "nama": name,
                "email": email,
                "password": generate_password_hash(password),
                "role": "user"
            }).execute()
            flash("Email OTP gagal dikirim (cek konfigurasi SMTP). Akun dibuat secara lokal.", "warning")
            return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/verify", methods=["GET", "POST"])
def verify():
    if request.method == "POST":
        otp_input = request.form.get("otp", "").strip()
        if otp_input and otp_input == session.get("reg_otp"):
            temp = session.get("reg_temp_user")
            if not temp:
                flash("Data registrasi tidak ditemukan di session.", "danger")
                return redirect(url_for("register"))

            supabase.table("users").insert({
                "nama": temp["name"],
                "email": temp["email"],
                "password": temp["password_hash"],
                "role": "user"
            }).execute()

            session.pop("reg_temp_user", None)
            session.pop("reg_otp", None)
            flash("Registrasi berhasil. Silakan login.", "success")
            return redirect(url_for("login"))
        else:
            flash("OTP salah. Coba lagi.", "danger")
    return render_template("verify.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = fetch_one(supabase.table("users").select("id,nama,email,password,role").eq("email", email))
        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["email"] = user["email"]
            session["role"] = user["role"]
            session["user_name"] = user["nama"]
            flash("Login berhasil.", "success")
            # redirect admin to dashboard
            if user["role"] == "admin":
                return redirect(url_for("dashboard"))
            return redirect(url_for("index"))
        else:
            flash("Email atau password salah.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Anda telah logout.", "info")
    return redirect(url_for("index"))

# ---------------- Admin Dashboard & Product Management ----------------
@app.route("/admin/dashboard")
@admin_required
def dashboard():
    # compute totals in Python (safe & consistent)
    orders_all = fetch_all(supabase.table("orders").select("id"))
    total_orders = len(orders_all) if orders_all is not None else 0

    products_all = fetch_all(supabase.table("products").select("stok"))
    total_stock = sum([p.get("stok", 0) for p in (products_all or [])])

    users_all = fetch_all(supabase.table("users").select("id"))
    total_users = len(users_all) if users_all is not None else 0

    # product list
    products = fetch_all(supabase.table("products").select("id,nama,harga,stok,rating").order("id", desc=True))

    # recent orders: fetch last 20 orders, then attach user & product names
    orders_raw = fetch_all(supabase.table("orders").select("*").order("tanggal", desc=True).limit(20))
    orders = []
    if orders_raw:
        for o in orders_raw:
            # fetch user and product for display (if available)
            user = fetch_one(supabase.table("users").select("nama").eq("id", o.get("user_id")))
            product = fetch_one(supabase.table("products").select("nama").eq("id", o.get("produk_id")))
            orders.append({
                "id": o.get("id"),
                "qty": o.get("quantity"),
                "status": o.get("status"),
                "tanggal": o.get("tanggal"),
                "user_nama": user.get("nama") if user else None,
                "produk_nama": product.get("nama") if product else None,
            })

    return render_template("dashboard.html",
                           total_orders=total_orders,
                           total_stock=total_stock,
                           total_users=total_users,
                           products=products,
                           orders=orders)

@app.route("/admin/add_product", methods=["GET", "POST"])
@admin_required
def add_product():
    if request.method == "POST":
        nama = request.form.get("nama", "").strip()
        harga = request.form.get("price", "0").replace(",", "")
        stok = int(request.form.get("stok", 0))
        rating = request.form.get("rating", "")
        if rating == "0" or rating == "":
            rating_val = None
        else:
            rating_val = float(rating)
        tag = request.form.get("tag", "")
        brand = request.form.get("brand", "")
        deskripsi = request.form.get("deskripsi", "")
        image_file = request.files.get("gambar")

        filename = None
        if image_file and allowed_file(image_file.filename):
            filename = secure_filename(image_file.filename)
            save_path = UPLOAD_FOLDER / filename
            image_file.save(save_path)

        supabase.table("products").insert({
            "nama": nama,
            "harga": float(harga) if harga else 0,
            "tag": tag,
            "brand": brand,
            "deskripsi": deskripsi,
            "gambar": filename,
            "rating": rating_val,
            "stok": stok
        }).execute()

        flash("Produk berhasil ditambahkan.", "success")
        return redirect(url_for("dashboard"))

    return render_template("add_product.html")

@app.route("/admin/edit_product/<int:produk_id>", methods=["GET", "POST"])
@admin_required
def edit_product(produk_id):
    product = fetch_one(supabase.table("products").select("*").eq("id", produk_id))
    if not product:
        flash("Produk tidak ditemukan.", "danger")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        nama = request.form.get("nama", "").strip()
        harga = request.form.get("harga", "0").replace(",", "")
        stok = int(request.form.get("stok", 0))
        rating = request.form.get("rating")
        rating = float(rating) if rating else None
        deskripsi = request.form.get("deskripsi", "")
        tag = request.form.get("tag", "")
        brand = request.form.get("brand", "")
        image_file = request.files.get("gambar")

        update_payload = {
            "nama": nama,
            "harga": float(harga) if harga else 0,
            "deskripsi": deskripsi,
            "rating": rating,
            "stok": stok,
            "tag": tag,
            "brand": brand
        }

        if image_file and allowed_file(image_file.filename):
            filename = secure_filename(image_file.filename)
            image_file.save(UPLOAD_FOLDER / filename)
            update_payload["gambar"] = filename

            # remove old image file if exists (same behavior as original)
            old_img = product.get("gambar")
            if old_img:
                try:
                    os.remove(UPLOAD_FOLDER / old_img)
                except Exception:
                    pass

        supabase.table("products").update(update_payload).eq("id", produk_id).execute()
        flash("Produk berhasil diperbarui.", "success")
        return redirect(url_for("dashboard"))

    return render_template("edit_product.html", product=product)

@app.route("/admin/delete_product/<int:produk_id>", methods=["POST"])
@admin_required
def delete_product(produk_id):
    product = fetch_one(supabase.table("products").select("gambar").eq("id", produk_id))
    if product and product.get("gambar"):
        try:
            os.remove(UPLOAD_FOLDER / product.get("gambar"))
        except Exception:
            pass

    supabase.table("products").delete().eq("id", produk_id).execute()
    flash("Produk dihapus.", "info")
    return redirect(url_for("dashboard"))

# ---------------- Chart Data (JSON for Chart.js) ----------------
@app.route("/admin/chart")
@admin_required
def chart():
    rows = fetch_all(supabase.table("products").select("nama,stok").order("stok", desc=True).limit(10))
    labels = [r.get("nama") for r in (rows or [])]
    data = [r.get("stok", 0) for r in (rows or [])]
    return render_template("chart.html", labels=labels, data=data)

# ---------------- Static images route (optional) ----------------
@app.route('/static/images/<path:filename>')
def images(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

@app.route('/setup_create_admin')
def setup_create_admin():
    existing_admin = fetch_one(supabase.table("users").select("id").eq("role", "admin").limit(1))
    if existing_admin:
        return "Admin already exists"
    pw = generate_password_hash("admin123")
    supabase.table("users").insert({
        "nama": "Admin",
        "email": "admin@example.com",
        "password": pw,
        "role": "admin"
    }).execute()
    return "Admin created: admin@example.com / admin123"

# route tambah ke cart
@app.route("/add_to_cart/<int:produk_id>")
@login_required
def add_to_cart(produk_id):
    user_id = session["user_id"]

    item = fetch_one(supabase.table("cart").select("*").eq("user_id", user_id).eq("produk_id", produk_id))
    if item:
        # update quantity
        new_qty = (item.get("quantity", 0) or 0) + 1
        supabase.table("cart").update({"quantity": new_qty}).eq("id", item.get("id")).execute()
    else:
        supabase.table("cart").insert({
            "user_id": user_id,
            "produk_id": produk_id,
            "quantity": 1
        }).execute()

    flash("Produk berhasil ditambahkan ke cart.", "success")
    return redirect(url_for("cart"))

# route tampilkan cart
@app.route("/cart")
@login_required
def cart():
    user_id = session["user_id"]
    cart_items = fetch_all(supabase.table("cart").select("*").eq("user_id", user_id))
    items = []
    if cart_items:
        for c in cart_items:
            p = fetch_one(supabase.table("products").select("id,nama,harga").eq("id", c.get("produk_id")))
            harga = p.get("harga", 0) if p else 0
            total = harga * (c.get("quantity", 0) or 0)
            items.append({
                "id": c.get("id"),
                "produk_id": c.get("produk_id"),
                "nama": p.get("nama") if p else "Produk tidak ditemukan",
                "harga": harga,
                "quantity": c.get("quantity", 0),
                "total": total
            })

    grand_total = sum([item["total"] for item in items]) if items else 0
    return render_template("cart.html", items=items, grand_total=grand_total)

# route hapus item dari cart
@app.route("/remove_from_cart/<int:cart_id>")
@login_required
def remove_from_cart(cart_id):
    user_id = session["user_id"]
    supabase.table("cart").delete().eq("id", cart_id).eq("user_id", user_id).execute()
    flash("Produk dihapus dari cart.", "info")
    return redirect(url_for("cart"))

@app.route("/checkout_cart", methods=["GET", "POST"])
@login_required
def checkout_cart():
    user_id = session["user_id"]

    # === Ambil isi keranjang ===
    cart_items = fetch_all(
        supabase.table("cart").select("*").eq("user_id", user_id)
    )
    if not cart_items:
        flash("Keranjang Anda kosong.", "warning")
        return redirect(url_for("cart"))

    # Gabungkan produk dengan detail
    items = []
    for c in cart_items:
        p = fetch_one(
            supabase.table("products")
            .select("id,nama,harga,tag,brand")
            .eq("id", c.get("produk_id"))
        )
        if p:
            items.append({
                "id": c.get("id"),
                "produk_id": c.get("produk_id"),
                "nama": p.get("nama"),
                "harga": p.get("harga"),
                "quantity": c.get("quantity", 0),
                "tag": p.get("tag"),
                "brand": p.get("brand"),
            })

    grand_total = sum(item["harga"] * item["quantity"] for item in items)

    # Hitung total quantity untuk ongkir flat
    total_qty = sum(item["quantity"] for item in items)
    ongkir = 20000 + (10000 * (total_qty - 1)) if total_qty > 0 else 0

    # Ambil alamat user
    addresses = fetch_all(
        supabase.table("user_addresses").select("*").eq("user_id", user_id)
    )

    # === Handle POST ===
    if request.method == "POST":
        # Tambah alamat baru
        if "add_address" in request.form:
            label = request.form.get("label")
            penerima = request.form.get("penerima")
            phone = request.form.get("phone")
            alamat = request.form.get("alamat")
            kota = request.form.get("kota")
            provinsi = request.form.get("provinsi")
            kode_pos = request.form.get("kode_pos")

            if label and penerima and phone and alamat and kota and provinsi and kode_pos:
                supabase.table("user_addresses").insert({
                    "user_id": user_id,
                    "label": label,
                    "penerima": penerima,
                    "phone": phone,
                    "alamat": alamat,
                    "kota": kota,
                    "provinsi": provinsi,
                    "kode_pos": kode_pos
                }).execute()
                flash("Alamat baru berhasil ditambahkan", "success")
            else:
                flash("Semua field alamat wajib diisi!", "danger")
            return redirect(url_for("checkout_cart"))

        # Proses checkout
        elif "checkout" in request.form:
            address_id = request.form.get("address_id")
            payment_method = request.form.get("payment_method")

            if not address_id:
                flash("Silakan pilih alamat pengiriman terlebih dahulu.", "danger")
                return redirect(url_for("checkout_cart"))

            # 1️⃣ Buat orders (header) → isi produk_id & quantity dari item pertama
            first_item = items[0] if items else None
            res_order = supabase.table("orders").insert({
                "user_id": user_id,
                "produk_id": first_item["produk_id"] if first_item else None,
                "quantity": first_item["quantity"] if first_item else 0,
                "status": "Pending",
                "payment_method": payment_method,
                "tanggal": datetime.utcnow().isoformat()
            }).execute()
            order_id = res_order.data[0]["id"]

            # 2️⃣ Buat order_items (detail produk)
            for item in items:
                supabase.table("order_items").insert({
                    "order_id": order_id,
                    "product_id": item["produk_id"],
                    "quantity": item["quantity"],
                    "total_price": item["harga"] * item["quantity"],
                    "status": "Pending"
                }).execute()

            # 3️⃣ Buat shipping (pakai address_id + ongkir flat)
            supabase.table("shipping").insert({
                "order_id": order_id,
                "address_id": int(address_id),
                "ongkir": float(ongkir),
                "status_pengiriman": "Pending",
                "created_at": datetime.utcnow().isoformat()
            }).execute()

            # 4️⃣ Clear cart
            supabase.table("cart").delete().eq("user_id", user_id).execute()

            flash(f"Pesanan berhasil dibuat dengan metode pembayaran: {payment_method}", "success")
            return redirect(url_for("payment", order_id=order_id))   # ⬅️ kirim order_id

    # === Render Template (GET atau fallback POST) ===
    return render_template(
        "checkout_cart.html",
        items=items,
        grand_total=grand_total,
        ongkir=ongkir,
        addresses=addresses,
    )

@app.route("/payment", methods=["GET", "POST"])
@login_required
def payment():
    user_id = session["user_id"]

    if request.method == "POST":
        form = request.form

        # 🔹 Ambil item terakhir dari cart sesuai user
        carts = fetch_all(
            supabase.table("cart")
            .select("id, produk_id, quantity, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
        )
        if not carts:
            flash("Keranjang kosong.", "danger")
            return redirect(url_for("cart"))

        # 🔹 Buat order baru
        order_data = {
            "user_id": user_id,
            "status": "Pending",
            "payment_method": "Midtrans",
            "tanggal": datetime.now().isoformat()
        }
        order_resp = supabase.table("orders").insert(order_data).execute()
        order_id = order_resp.data[0]["id"]

        # 🔹 Masukkan items ke order_items
        order_items = []
        for c in carts:
            product = fetch_one(
                supabase.table("products").select("id, nama, harga").eq("id", c["produk_id"])
            )
            if not product:
                continue

            total_price = product["harga"] * c["quantity"]
            supabase.table("order_items").insert({
                "order_id": order_id,
                "product_id": product["id"],
                "quantity": c["quantity"],
                "total_price": total_price,
                "status": "Pending",
                "time_stamp": datetime.now().isoformat()
            }).execute()

            order_items.append({
                "id": str(product["id"]),
                "price": int(product["harga"]),
                "quantity": int(c["quantity"]),
                "name": product["nama"][:50]
            })

        # 🔹 Hitung ongkir (flat)
        total_qty = sum(c["quantity"] for c in carts)
        ongkir = 20000 + (10000 * (total_qty - 1)) if total_qty > 0 else 0

        subtotal = sum([oi["price"] * oi["quantity"] for oi in order_items])
        total_bayar = subtotal + ongkir

        # 🔹 Simpan alamat baru
        addr_resp = supabase.table("user_addresses").insert({
            "user_id": user_id,
            "label": form.get("label", "Alamat Utama"),
            "penerima": form.get("penerima"),
            "phone": form.get("phone"),
            "alamat": form.get("alamat"),
            "kota": form.get("kota"),
            "provinsi": form.get("provinsi"),
            "kode_pos": form.get("kode_pos"),
            "is_default": True
        }).execute()
        address_id = addr_resp.data[0]["address_id"]

        # 🔹 Simpan shipping
        supabase.table("shipping").insert({
            "order_id": order_id,
            "address_id": address_id,
            "kurir": "SPX",
            "service": "reguler",
            "ongkir": ongkir,
            "resi": "RESI" + str(random.randint(100000, 999999)),
            "status_pengiriman": "Belum Dikirim"
        }).execute()

        # 🔹 Buat transaksi Midtrans
        snap_resp = create_transaction(order_id, total_bayar, order_items, ongkir)
        snap_redirect_url = snap_resp["redirect_url"]

        return redirect(snap_redirect_url)

    # ======================
    # GET → Tampilkan ringkasan
    # ======================
    order = fetch_one(
        supabase.table("orders").select("*").eq("user_id", user_id).order("tanggal", desc=True).limit(1)
    )
    if not order:
        flash("Belum ada pesanan untuk dibayar.", "warning")
        return redirect(url_for("cart"))

    order_items = fetch_all(
        supabase.table("order_items")
        .select("product_id,quantity,total_price")
        .eq("order_id", order["id"])
    )

    items = []
    subtotal = 0
    for oi in order_items:
        product = fetch_one(
            supabase.table("products").select("nama,harga,brand,tag").eq("id", oi["product_id"])
        )
        if product:
            items.append({
                "nama": product["nama"],
                "harga": product["harga"],
                "brand": product.get("brand"),
                "tag": product.get("tag"),
                "quantity": oi["quantity"],
                "total_price": oi["total_price"],
            })
            subtotal += oi["total_price"]

    shipping = fetch_one(supabase.table("shipping").select("*").eq("order_id", order["id"]))
    ongkir = shipping.get("ongkir", 0) if shipping else 0
    final_total = subtotal + ongkir

    address = fetch_one(
        supabase.table("user_addresses").select("*").eq("user_id", user_id).order("address_id", desc=True).limit(1)
    )

    return render_template(
        "payment.html",
        order=order,
        items=items,
        subtotal=subtotal,
        final_total=final_total,
        address=address,
    )

# ---------------- Run ----------------
if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)