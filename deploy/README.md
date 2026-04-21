# Deploy — Ubuntu EC2

Assumes the repo is at `/home/ubuntu/mcp-app/mcp_db_transactions` and the
virtualenv is at `./venv/`. If yours differ, edit the paths in
`transaction-analysis.service` before installing.

## 1. Install the systemd service

```bash
sudo cp deploy/transaction-analysis.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now transaction-analysis
sudo systemctl status transaction-analysis
```

## 2. Manage it

```bash
sudo systemctl restart transaction-analysis      # after code / .env changes
sudo systemctl stop transaction-analysis
sudo journalctl -u transaction-analysis -f       # live logs
sudo journalctl -u transaction-analysis -n 100   # last 100 lines
```

## 3. Open the port in the EC2 Security Group

Inbound rule → Custom TCP 8501 from your IP (or 0.0.0.0/0 for a public demo).

Then visit: `http://<EC2_PUBLIC_IP>:8501`

## 4. (Optional) Nginx reverse proxy + HTTPS

```bash
sudo apt install -y nginx certbot python3-certbot-nginx

sudo cp deploy/nginx-transaction-analysis.conf /etc/nginx/sites-available/transaction-analysis
# edit server_name to your domain
sudo nano /etc/nginx/sites-available/transaction-analysis

sudo ln -sf /etc/nginx/sites-available/transaction-analysis /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

# HTTPS — DNS must already point at the EC2 IP
sudo certbot --nginx -d your-domain.example.com
```

After Nginx is in place, open ports **80** and **443** in the Security Group
and optionally remove the 8501 rule (Streamlit can then bind only to
127.0.0.1 — add `--server.address 127.0.0.1` in the service ExecStart).

## 5. Verify

```bash
curl -sI http://127.0.0.1:8501 | head -1         # HTTP/1.1 200 OK
```
