from flask import Flask, render_template, request, redirect, url_for, session
import pandas as pd
import folium
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Change for production


# Theme helper: inject current theme into templates
@app.context_processor
def inject_theme():
    # Default to 'light' if not set
    theme = session.get('theme', None)
    return {'theme': theme}


@app.route('/set_theme', methods=['POST'])
def set_theme():
    # Expect JSON or form with 'theme' == 'light' or 'dark' or 'system'
    theme = request.form.get('theme') or (request.json.get('theme') if request.is_json else None)
    if theme not in ('light', 'dark', 'system', None):
        return ('Invalid theme', 400)
    # Save preference in session
    if theme == 'system' or theme is None:
        session.pop('theme', None)
    else:
        session['theme'] = theme
    return ('', 204)

# Load all CSVs with error handling
try:
    minerals_df = pd.read_csv('data/minerals.csv')
    extra_minerals_df = pd.read_csv('data/extra_minerals.csv')
    minerals_df = pd.concat([minerals_df, extra_minerals_df], ignore_index=True)  # Merge XLSX data
    minerals = minerals_df.set_index('MineralName').to_dict('index')
except Exception as e:
    print(f"Error loading minerals: {e}")
    minerals = {}  # Fallback empty dict

try:
    countries_df = pd.read_csv('data/countries.csv')
    countries = countries_df.set_index('CountryName').to_dict('index')
except Exception as e:
    print(f"Error loading countries: {e}")
    countries = {}

try:
    production_df = pd.read_csv('data/production_stats.csv')
    # Fixed merge: Index lookup DFs on IDs for proper names
    minerals_indexed = minerals_df.set_index('MineralID')
    countries_indexed = countries_df.set_index('CountryID')
    production_df = production_df.merge(minerals_indexed[['MineralName']], left_on='MineralID', right_index=True, how='left')
    production_df = production_df.merge(countries_indexed[['CountryName']], left_on='CountryID', right_index=True, how='left')
    df = production_df.rename(columns={'MineralName': 'mineral', 'CountryName': 'country'})
except Exception as e:
    print(f"Error loading production: {e}")
    df = pd.DataFrame()  # Empty DF

try:
    users_df = pd.read_csv('data/users.csv')
    users = users_df.set_index('Username').to_dict('index')
except Exception as e:
    print(f"Error loading users: {e}")
    users = {}

try:
    roles_df = pd.read_csv('data/roles.csv')
    PERMISSIONS = {}
    for _, row in roles_df.iterrows():
        role_name = row['RoleName']
        perms_str = row['Permissions']
        if role_name == 'Administrator':
            PERMISSIONS[role_name] = ['all']
        elif role_name == 'Investor':
            # View country profiles, charts, production
            PERMISSIONS[role_name] = ['profiles', 'charts', 'production']
        elif role_name == 'Researcher':
            # View/export mineral & country data, add insights, view country profiles, view map
            PERMISSIONS[role_name] = ['database', 'export', 'insights', 'profiles', 'map']
        else:
            PERMISSIONS[role_name] = []
except Exception as e:
    print(f"Error loading roles: {e}")
    PERMISSIONS = {}

try:
    sites_df = pd.read_csv('data/sites.csv')
    # Fixed merge for sites (same indexing)
    minerals_indexed = minerals_df.set_index('MineralID')
    countries_indexed = countries_df.set_index('CountryID')
    sites_df = sites_df.merge(minerals_indexed[['MineralName']], left_on='MineralID', right_index=True, how='left')
    sites_df = sites_df.merge(countries_indexed[['CountryName']], left_on='CountryID', right_index=True, how='left')
    sites = sites_df.to_dict('records')
    # Validate site coordinates against approximate country centroids and auto-correct obvious mismatches.
    # This prevents markers appearing in the wrong hemisphere when coordinates were mixed up or countries mis-assigned.
    country_centroids = {
        'DRC (Congo)': (-4.038333, 21.758664),
        'South Africa': (-30.559482, 22.937506),
        'Mozambique': (-18.665695, 35.529562),
        'Namibia': (-22.9576, 18.4904),
    }
    corrections = []
    corrected_sites = []
    for s in sites:
        try:
            lat = float(s.get('Latitude', 0))
            lon = float(s.get('Longitude', 0))
        except Exception:
            corrected_sites.append(s)
            continue
        cname = s.get('CountryName')
        if cname in country_centroids:
            c_lat, c_lon = country_centroids[cname]
            # If the site is more than ~10 deg latitude or ~20 deg longitude away from the country centroid,
            # treat it as an obvious mismatch and snap it to the centroid (will correct Australia vs South Africa errors).
            if abs(lat - c_lat) > 10 or abs(lon - c_lon) > 20:
                # Detected a large discrepancy between site coords and assigned country centroid.
                # Common data issues: lat/lon swapped or wrong sign. Try swapping lat/lon first and see
                # if that brings the point closer to the country centroid. If so, apply the swap.
                swapped_lat, swapped_lon = lon, lat
                dist_orig = abs(lat - c_lat) + abs(lon - c_lon)
                dist_swapped = abs(swapped_lat - c_lat) + abs(swapped_lon - c_lon)
                note = ''
                if dist_swapped < dist_orig:
                    corrections.append({'SiteID': s.get('SiteID'), 'SiteName': s.get('SiteName'), 'CountryName': cname,
                                        'action': 'swap_latlon', 'old': (lat, lon), 'new': (swapped_lat, swapped_lon)})
                    s['Latitude'] = swapped_lat
                    s['Longitude'] = swapped_lon
                    note = 'Swapped lat/lon due to large mismatch with country centroid.'
                else:
                    # Do not snap to centroid automatically (data could be for a country not in our list).
                    corrections.append({'SiteID': s.get('SiteID'), 'SiteName': s.get('SiteName'), 'CountryName': cname,
                                        'action': 'mismatch', 'old': (lat, lon), 'country_centroid': (c_lat, c_lon)})
                    note = 'Coordinate far from assigned country centroid; left unchanged for manual review.'
                # Attach a note field for downstream CSV / debugging
                s['Note'] = note
        corrected_sites.append(s)
    sites = corrected_sites
    if corrections:
        print('Site coordinate corrections applied:')
        for c in corrections:
            if c.get('action') == 'swap_latlon':
                print(f" - Site {c['SiteID']} ({c['SiteName']}) in {c['CountryName']}: swapped {c['old']} -> {c['new']}")
            elif c.get('action') == 'mismatch':
                print(f" - Site {c['SiteID']} ({c['SiteName']}) in {c['CountryName']}: mismatch {c['old']} (country centroid {c.get('country_centroid')})")
            else:
                # Generic fallback
                old = c.get('old')
                new = c.get('new')
                print(f" - Site {c.get('SiteID')} ({c.get('SiteName')}): {old} -> {new}")
        try:
            # Save a backup with the corrected coordinates so changes are visible to the user.
            sites_df_corrected = pd.DataFrame(sites)
            sites_df_corrected.to_csv('data/sites_fixed.csv', index=False)
            print('Wrote corrected sites to data/sites_fixed.csv')
        except Exception as e:
            print(f'Failed to write corrected sites CSV: {e}')
except Exception as e:
    print(f"Error loading sites: {e}")
    sites = []

@app.route('/')
def index():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in users and users[username]['PasswordHash'] == password:
            session['user'] = username
            role_id = users[username]['RoleID']
            role_name = roles_df[roles_df['RoleID'] == role_id]['RoleName'].iloc[0] if not roles_df.empty else 'Unknown'
            session['role'] = role_name
            # Auto-redirect to dashboard with success message
            return redirect(url_for('dashboard', success='Login successful!'))
        else:
            error = 'Invalid credentials. Try again.'
            return render_template('login.html', error=error)
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/dashboard')
def dashboard():
    success = request.args.get('success')  # Get success from redirect URL
    if 'user' not in session:
        return redirect(url_for('login'))
    role = session['role']
    allowed_features = []
    is_admin = False
    if 'all' in PERMISSIONS.get(role, []) or 'database' in PERMISSIONS.get(role, []):
        allowed_features.append('database')
    if 'all' in PERMISSIONS.get(role, []) or 'profiles' in PERMISSIONS.get(role, []):
        allowed_features.append('profiles')
    if 'all' in PERMISSIONS.get(role, []) or 'charts' in PERMISSIONS.get(role, []):
        allowed_features.append('charts')
    if 'all' in PERMISSIONS.get(role, []) or 'map' in PERMISSIONS.get(role, []):
        allowed_features.append('map')
    if 'all' in PERMISSIONS.get(role, []):
        is_admin = True
    num_countries = len(countries)
    num_minerals = len(minerals)
    num_sites = len(sites)
    return render_template('dashboard.html', role=role, features=allowed_features, success=success, num_countries=num_countries, num_minerals=num_minerals, num_sites=num_sites, is_admin=is_admin)



# Admin panel for editing, adding, and deleting data
@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if 'user' not in session or 'all' not in PERMISSIONS.get(session['role'], []):
        return redirect(url_for('dashboard'))
    message = None
    global minerals, countries, sites
    if request.method == 'POST':
        action = request.form.get('action')
        # Mineral edit
        if action == 'edit_mineral':
            mineral_name = request.form.get('mineral_name')
            description = request.form.get('description')
            price = request.form.get('market_price')
            if mineral_name in minerals:
                minerals[mineral_name]['Description'] = description
                minerals[mineral_name]['MarketPriceUSD_per_tonne'] = price
                message = f"Updated {mineral_name}. (Note: Changes are in-memory and not persisted to CSV.)"
            else:
                message = f"Mineral {mineral_name} not found."
        # Mineral delete
        elif action == 'delete_mineral':
            mineral_name = request.form.get('mineral_name')
            if mineral_name in minerals:
                del minerals[mineral_name]
                message = f"Deleted {mineral_name}. (In-memory only.)"
            else:
                message = f"Mineral {mineral_name} not found."
        # Add country
        elif action == 'add_country':
            country_name = request.form.get('country_name')
            gdp = request.form.get('gdp')
            mining_revenue = request.form.get('mining_revenue')
            key_projects = request.form.get('key_projects')
            if country_name and country_name not in countries:
                countries[country_name] = {
                    'GDP_BillionUSD': gdp,
                    'MiningRevenue_BillionUSD': mining_revenue,
                    'KeyProjects': key_projects
                }
                message = f"Added country {country_name}. (In-memory only.)"
            else:
                message = f"Country {country_name} already exists or invalid."
        # Delete country
        elif action == 'delete_country':
            country_name = request.form.get('country_name')
            if country_name in countries:
                del countries[country_name]
                message = f"Deleted country {country_name}. (In-memory only.)"
            else:
                message = f"Country {country_name} not found."
        # Add site
        elif action == 'add_site':
            site_name = request.form.get('site_name')
            country_name = request.form.get('site_country')
            mineral_name = request.form.get('site_mineral')
            latitude = request.form.get('latitude')
            longitude = request.form.get('longitude')
            production = request.form.get('production')
            if site_name and country_name in countries and mineral_name in minerals:
                new_site = {
                    'SiteName': site_name,
                    'CountryName': country_name,
                    'MineralName': mineral_name,
                    'Latitude': float(latitude),
                    'Longitude': float(longitude),
                    'Production_tonnes': int(production)
                }
                sites.append(new_site)
                message = f"Added site {site_name}. (In-memory only.)"
            else:
                message = f"Invalid site data or missing country/mineral."
        # Delete site
        elif action == 'delete_site':
            site_name = request.form.get('site_name')
            found = False
            for i, s in enumerate(sites):
                if s.get('SiteName') == site_name:
                    del sites[i]
                    found = True
                    message = f"Deleted site {site_name}. (In-memory only.)"
                    break
            if not found:
                message = f"Site {site_name} not found."
    return render_template('admin.html', minerals=minerals, countries=countries, sites=sites, message=message)


# In-memory insights storage
insights = []

@app.route('/mineral_database', methods=['GET', 'POST'])
def mineral_database():
    if 'user' not in session or ('database' not in PERMISSIONS.get(session['role'], []) and 'all' not in PERMISSIONS.get(session['role'], [])):
        return redirect(url_for('dashboard'))
    message = None
    search_query = request.args.get('search', '').strip().lower()
    filtered_minerals = minerals
    if search_query:
        filtered_minerals = {k: v for k, v in minerals.items() if search_query in k.lower() or search_query in v.get('Description','').lower()}
    # Allow researchers to add insights
    if request.method == 'POST' and 'insight' in request.form:
        user = session.get('user', 'unknown')
        role = session.get('role', '')
        # Only allow researchers (or those with 'insights' permission) to add insights
        if role == 'Researcher' or 'insights' in PERMISSIONS.get(role, []):
            insight = request.form.get('insight')
            if insight:
                insights.append({'user': user, 'insight': insight, 'type': 'mineral'})
                message = 'Insight added.'
        else:
            message = 'You do not have permission to add insights.'
    return render_template('mineral_database.html', minerals=filtered_minerals, insights=[i for i in insights if i['type']=='mineral'], message=message, search_query=search_query)

# Download PDF of mineral data (researcher only)
@app.route('/download/minerals.pdf')
def download_minerals_pdf():
    if 'user' not in session or (session['role'] != 'Researcher' and 'all' not in PERMISSIONS.get(session['role'], [])):
        return redirect(url_for('dashboard'))
    from io import BytesIO
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.setFont("Helvetica", 12)
    y = 750
    p.drawString(30, y, "Mineral Data Export")
    y -= 30
    for mineral, info in minerals.items():
        p.drawString(30, y, f"{mineral}: {info.get('Description','')} | ${info.get('MarketPriceUSD_per_tonne','')}")
        y -= 20
        if y < 50:
            p.showPage()
            y = 750
    p.save()
    buffer.seek(0)
    return app.response_class(buffer, mimetype='application/pdf', headers={"Content-Disposition": "attachment;filename=minerals.pdf"})

# Download PDF of country data (researcher only)
@app.route('/download/countries.pdf')
def download_countries_pdf():
    if 'user' not in session or (session['role'] != 'Researcher' and 'all' not in PERMISSIONS.get(session['role'], [])):
        return redirect(url_for('dashboard'))
    from io import BytesIO
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.setFont("Helvetica", 12)
    y = 750
    p.drawString(30, y, "Country Data Export")
    y -= 30
    for country, info in countries.items():
        p.drawString(30, y, f"{country}: GDP ${info.get('GDP_BillionUSD','')}B | Mining Revenue ${info.get('MiningRevenue_BillionUSD','')}B | Projects: {info.get('KeyProjects','')}")
        y -= 20
        if y < 50:
            p.showPage()
            y = 750
    p.save()
    buffer.seek(0)
    return app.response_class(buffer, mimetype='application/pdf', headers={"Content-Disposition": "attachment;filename=countries.pdf"})


@app.route('/country_profiles', methods=['GET', 'POST'])
def country_profiles():
    if 'user' not in session or ('profiles' not in PERMISSIONS.get(session['role'], []) and 'all' not in PERMISSIONS.get(session['role'], [])):
        return redirect(url_for('dashboard'))
    message = None
    search_query = request.args.get('search', '').strip().lower()
    filtered_countries = countries
    if search_query:
        filtered_countries = {k: v for k, v in countries.items() if search_query in k.lower() or search_query in v.get('KeyProjects','').lower()}
    # Allow researchers to add insights
    if request.method == 'POST' and 'insight' in request.form:
        user = session.get('user', 'unknown')
        role = session.get('role', '')
        # Only allow researchers (or those with 'insights' permission) to add insights
        if role == 'Researcher' or 'insights' in PERMISSIONS.get(role, []):
            insight = request.form.get('insight')
            if insight:
                insights.append({'user': user, 'insight': insight, 'type': 'country'})
                message = 'Insight added.'
        else:
            message = 'You do not have permission to add insights.'
    return render_template('country_profiles.html', countries=filtered_countries, insights=[i for i in insights if i['type']=='country'], message=message, search_query=search_query)

@app.route('/interactive_charts')
def interactive_charts():
    if 'user' not in session or ('charts' not in PERMISSIONS.get(session['role'], []) and 'all' not in PERMISSIONS.get(session['role'], [])):
        return redirect(url_for('dashboard'))
    # Basic filters for interactivity (Appendix A)
    mineral_filter = request.args.get('mineral', 'all')
    country_filter = request.args.get('country', 'all')
    filtered_df = df.copy()
    if mineral_filter != 'all':
        filtered_df = filtered_df[filtered_df['mineral'] == mineral_filter]
    if country_filter != 'all':
        filtered_df = filtered_df[filtered_df['country'] == country_filter]
    # Fixed charts: Ensure data has names/values, fallback to full df if empty
    if filtered_df.empty:
        filtered_df = df.copy()

    # Ensure essential columns exist and have proper dtypes
    if 'Year' not in filtered_df.columns:
        filtered_df['Year'] = pd.Series(dtype=int)
    # Cast numeric columns safely
    for col in ['Production_tonnes', 'ExportValue_BillionUSD']:
        if col in filtered_df.columns:
            filtered_df[col] = pd.to_numeric(filtered_df[col], errors='coerce')

    # Choose color/hover columns defensively
    color_col = 'mineral' if 'mineral' in filtered_df.columns else 'MineralID' if 'MineralID' in filtered_df.columns else None
    country_col = 'country' if 'country' in filtered_df.columns else 'CountryID' if 'CountryID' in filtered_df.columns else None

    # If dataset is still effectively empty, produce placeholder figures
    if filtered_df.empty or filtered_df['Production_tonnes'].dropna().empty:
        import plotly.graph_objects as go
        fig_prod = go.Figure()
        fig_prod.add_annotation(text='No production data available for selected filters', xref='paper', yref='paper', showarrow=False)
        fig_prod.update_layout(template='plotly_white', height=420, margin=dict(t=60, b=40, l=60, r=20))
        chart_div = fig_prod.to_html(full_html=False, include_plotlyjs='cdn', config={'responsive': True})
    else:
        # Production as bar (better for categorical data)
        fig_prod = px.bar(filtered_df, x='Year', y='Production_tonnes', color=color_col, barmode='group',
                          title=f'Production Trends {mineral_filter if mineral_filter != "all" else ""} in {country_filter if country_filter != "all" else ""}',
                          hover_data=[c for c in (country_col, 'ExportValue_BillionUSD') if c], labels={'Production_tonnes': 'Tonnes'})
        fig_prod.update_layout(template='plotly_white', height=420, legend_title_text='Mineral/Group', xaxis_title='Year', yaxis_title='Production (Tonnes)', margin=dict(t=60, b=40, l=60, r=20))
        fig_prod.update_traces(marker_line_width=0.5)
        chart_div = fig_prod.to_html(full_html=False, include_plotlyjs='cdn', config={'responsive': True})

    # Export as line (trends)
    if filtered_df.empty or filtered_df['ExportValue_BillionUSD'].dropna().empty:
        import plotly.graph_objects as go
        fig_export = go.Figure()
        fig_export.add_annotation(text='No export value data available for selected filters', xref='paper', yref='paper', showarrow=False)
        fig_export.update_layout(template='plotly_white', height=420, margin=dict(t=60, b=40, l=60, r=20))
        price_div = fig_export.to_html(full_html=False, include_plotlyjs=False, config={'responsive': True})
    else:
        fig_export = px.line(filtered_df, x='Year', y='ExportValue_BillionUSD', color=color_col,
                             title=f'Export Value Trends {mineral_filter if mineral_filter != "all" else ""} in {country_filter if country_filter != "all" else ""}',
                             hover_data=[c for c in (country_col, 'Production_tonnes') if c], labels={'ExportValue_BillionUSD': 'Billion USD'})
        fig_export.update_layout(template='plotly_white', height=420, legend_title_text='Mineral/Group', xaxis_title='Year', yaxis_title='Export Value (Billion USD)', margin=dict(t=60, b=40, l=60, r=20))
        fig_export.update_traces(mode='lines+markers')
        # Use include_plotlyjs=False for the second chart since the first already includes the CDN script
        price_div = fig_export.to_html(full_html=False, include_plotlyjs=False, config={'responsive': True})

    return render_template('interactive_charts.html', chart_div=chart_div, price_div=price_div, minerals=list(minerals.keys()), countries=list(countries.keys()))

@app.route('/geographical_map')
def geographical_map():
    if 'user' not in session or ('map' not in PERMISSIONS.get(session['role'], []) and 'all' not in PERMISSIONS.get(session['role'], [])):
        return redirect(url_for('dashboard'))
    # Basic filter for map (Appendix A: alternatives/deposits)
    mineral_filter = request.args.get('mineral', 'all')
    filtered_sites = sites
    if mineral_filter != 'all':
        filtered_sites = [s for s in sites if s.get('MineralName') == mineral_filter]
    m = folium.Map(location=[0, 20], zoom_start=3, tiles=None, attr='Google Maps (English)')
    # Google Satellite default (English labels, real imagery)
    folium.TileLayer(tiles='https://mt1.google.com/vt/lyrs=s,h&x={x}&y={y}&z={z}&hl=en', 
                     attr='Google Satellite (English)', name='Google Satellite (English)', overlay=False, control=True).add_to(m)
    # Google Roadmap for streets (English)
    folium.TileLayer(tiles='https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}&hl=en', 
                     attr='Google Roadmap (English)', name='Google Roadmap (English)', overlay=False, control=True).add_to(m)
    # (Removed OpenStreetMap fallback per user request; only Google Satellite and Roadmap layers remain)
    folium.LayerControl().add_to(m)
    for site in filtered_sites:
        folium.Marker([site['Latitude'], site['Longitude']], popup=f"{site['SiteName']} - {site.get('MineralName', 'Unknown')} in {site.get('CountryName', 'Unknown')} ({site['Production_tonnes']} tonnes)").add_to(m)
    map_html = m._repr_html_()
    return render_template('geographical_map.html', map_html=map_html, minerals=list(minerals.keys()))

if __name__ == '__main__':
    app.run(debug=True)