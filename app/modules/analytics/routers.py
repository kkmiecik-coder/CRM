# modules/analytics/routers.py

from flask import Blueprint, render_template, jsonify, current_app, session, request, send_file
from modules.public_calculator.models import PublicSession
from sqlalchemy import func
from extensions import db
import os
import json
os.environ['OPENBLAS_NUM_THREADS'] = '1'
import pandas as pd
from io import BytesIO
import zipfile
from datetime import datetime

# Import nowych funkcji analitycznych
from .models import (
    AnalyticsQueries, 
    AnalyticsExportHelper
)

analytics_bp = Blueprint("analytics", __name__,
                         template_folder="templates",
                         static_folder="static")

@analytics_bp.route("/analytics")
def analytics_dashboard():
    """Główny dashboard analytics z podstawowymi danymi dla wszystkich zakładek"""
    
    # Dane dla kalkulatora publicznego (istniejące)
    total_sessions = db.session.query(func.count(PublicSession.id)).scalar()
    avg_duration = db.session.query(func.avg(PublicSession.duration_ms)).scalar() or 0
    avg_duration_sec = round(avg_duration / 1000, 2)
    color_sessions = db.session.query(func.count()).filter(PublicSession.color.isnot(None)).scalar()
    variant_sessions = db.session.query(func.count()).filter(PublicSession.variant.isnot(None)).scalar()
    
    # Podstawowe dane dla innych zakładek (do szybkiego ładowania)
    sales_kpi = AnalyticsQueries.get_sales_kpi_data()
    team_count = len(AnalyticsQueries.get_team_performance_data())
    top_clients_count = len(AnalyticsQueries.get_clients_analytics_data(5))  # tylko top 5 dla preview
    baselinker_basic = AnalyticsQueries.get_baselinker_analytics_data()
    
    user_email = session.get("user_email")

    return render_template(
        "analytics.html",
        # Dane public calculator (istniejące)
        total_sessions=total_sessions,
        avg_duration_sec=avg_duration_sec,
        color_sessions=color_sessions,
        variant_sessions=variant_sessions,
        # Podstawowe dane innych zakładek
        sales_kpi=sales_kpi,
        team_count=team_count,
        top_clients_count=top_clients_count,
        baselinker_conversion=baselinker_basic['conversion_rate'],
        user_email=user_email
    )

# =====================================
# ENDPOINTY DANYCH DLA POSZCZEGÓLNYCH ZAKŁADEK
# =====================================

@analytics_bp.route("/data/public-calc")
def public_calc_data():
    """Dane dla zakładki kalkulatora publicznego (istniejące, zrefaktorowane)"""
    print("[public_calc_data] Endpoint hit!")

    variants_query = db.session.query(PublicSession.variant, func.count()).group_by(PublicSession.variant).all()
    finishings_query = db.session.query(PublicSession.finishing, func.count()).group_by(PublicSession.finishing).all()
    colors_query = db.session.query(PublicSession.color, func.count()).group_by(PublicSession.color).all()

    # Parsowanie wymiarów z JSON w kolumnie 'inputs'
    dims_raw = db.session.query(PublicSession.inputs).all()
    dims_counter = {}
    for row in dims_raw:
        try:
            data = json.loads(row[0])
            key = f"{data.get('length', '?')}x{data.get('width', '?')}x{data.get('thickness', '?')}"
            dims_counter[key] = dims_counter.get(key, 0) + 1
        except (json.JSONDecodeError, TypeError, AttributeError):
            continue

    # Format danych dla Chart.js
    def format_chart_data(query_result, label):
        labels = [str(item[0]) if item[0] else "Brak danych" for item in query_result]
        values = [item[1] for item in query_result]
        return {"label": label, "labels": labels, "values": values}

    dims_labels = list(dims_counter.keys())[:10]  # Top 10
    dims_values = [dims_counter[key] for key in dims_labels]

    return jsonify({
        "variants": format_chart_data(variants_query, "Warianty"),
        "finishings": format_chart_data(finishings_query, "Wykończenia"),
        "colors": format_chart_data(colors_query, "Kolory"),
        "dimensions": {"label": "Wymiary", "labels": dims_labels, "values": dims_values}
    })

@analytics_bp.route("/data/sales")
def sales_data():
    """Dane dla zakładki sprzedaży"""
    
    try:
        # KPI
        kpi_data = AnalyticsQueries.get_sales_kpi_data()
        
        # Trendy
        trends_data = AnalyticsQueries.get_sales_trends_data()
        
        # Popularne produkty
        products_data = AnalyticsQueries.get_popular_products_data()
        
        return jsonify({
            'success': True,
            'kpi': kpi_data,
            'trends': trends_data,
            'popular_products': products_data
        })
        
    except Exception as e:
        current_app.logger.error(f"Błąd w sales_data: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@analytics_bp.route("/data/team")
def team_data():
    """Dane dla zakładki zespołu"""
    
    try:
        team_performance = AnalyticsQueries.get_team_performance_data()
        
        return jsonify({
            'success': True,
            'team_performance': team_performance
        })
        
    except Exception as e:
        current_app.logger.error(f"Błąd w team_data: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@analytics_bp.route("/data/clients")
def clients_data():
    """Dane dla zakładki klientów"""
    
    try:
        # Top klienci
        top_clients = AnalyticsQueries.get_clients_analytics_data()
        
        # Geografia i źródła
        geography_stats = AnalyticsQueries.get_geography_stats()
        
        return jsonify({
            'success': True,
            'top_clients': top_clients,
            'geography': geography_stats
        })
        
    except Exception as e:
        current_app.logger.error(f"Błąd w clients_data: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@analytics_bp.route("/data/baselinker")
def baselinker_data():
    """Dane dla zakładki Baselinker"""
    
    try:
        baselinker_analytics = AnalyticsQueries.get_baselinker_analytics_data()
        
        return jsonify({
            'success': True,
            'baselinker': baselinker_analytics
        })
        
    except Exception as e:
        current_app.logger.error(f"Błąd w baselinker_data: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# =====================================
# ENDPOINTY EXPORTU
# =====================================

@analytics_bp.route("/export/<export_type>/<format>")
def export_data(export_type, format):
    """
    Eksport danych do Excel lub CSV
    export_type: sales, team, clients, baselinker, public_calc
    format: xlsx, csv
    """
    print(f"[EXPORT DEBUG] Otrzymano: {export_type}, {format}")
    
    try:
        if format not in ['xlsx', 'csv']:
            return jsonify({'error': 'Nieprawidłowy format. Użyj xlsx lub csv'}), 400
        
        if export_type not in ['sales', 'team', 'clients', 'baselinker', 'public_calc']:
            return jsonify({'error': 'Nieprawidłowy typ exportu'}), 400
        
        # Przygotowanie danych do exportu
        if export_type == 'sales':
            data = AnalyticsExportHelper.prepare_sales_export_data()
            filename = f'analytics_sprzedaz_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
            
        elif export_type == 'team':
            data = {'team_performance': AnalyticsExportHelper.prepare_team_export_data()}
            filename = f'analytics_zespol_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
            
        elif export_type == 'clients':
            data = AnalyticsExportHelper.prepare_clients_export_data()
            filename = f'analytics_klienci_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
            
        elif export_type == 'baselinker':
            data = AnalyticsExportHelper.prepare_baselinker_export_data()
            filename = f'analytics_baselinker_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
            
        elif export_type == 'public_calc':
            # Przygotuj dane kalkulatora publicznego
            data = prepare_public_calc_export_data()
            filename = f'analytics_kalkulator_publiczny_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        
        # Eksport do Excel
        if format == 'xlsx':
            return export_to_excel(data, filename, export_type)
        
        # Eksport do CSV
        elif format == 'csv':
            return export_to_csv(data, filename, export_type)
            
    except Exception as e:
        current_app.logger.error(f"Błąd podczas exportu {export_type} do {format}: {str(e)}")
        return jsonify({'error': f'Błąd podczas exportu: {str(e)}'}), 500


def export_to_excel(data: dict, filename: str, export_type: str):
    """Eksportuje dane do pliku Excel"""
    
    try:
        output = BytesIO()
        
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            
            if export_type == 'sales':
                # Arkusz KPI
                kpi_df = pd.DataFrame(data['kpi'])
                kpi_df.to_excel(writer, sheet_name='KPI', index=False)
                
                # Arkusz Trendy
                trends_df = pd.DataFrame(data['trends'])
                trends_df.to_excel(writer, sheet_name='Trendy_miesięczne', index=False)
                
            elif export_type == 'team':
                # Arkusz Performance zespołu
                team_df = pd.DataFrame(data['team_performance'])
                team_df.to_excel(writer, sheet_name='Performance_zespołu', index=False)
                
            elif export_type == 'clients':
                # Arkusz Top Klienci
                clients_df = pd.DataFrame(data['top_clients'])
                clients_df.to_excel(writer, sheet_name='Top_klienci', index=False)
                
                # Arkusz Miasta
                cities_df = pd.DataFrame(data['cities'])
                cities_df.to_excel(writer, sheet_name='Statystyki_miast', index=False)
                
                # Arkusz Źródła
                sources_df = pd.DataFrame(data['sources'])
                sources_df.to_excel(writer, sheet_name='Źródła_klientów', index=False)
                
            elif export_type == 'baselinker':
                # Arkusz Statystyki logów
                logs_df = pd.DataFrame(data['logs_stats'])
                logs_df.to_excel(writer, sheet_name='Statystyki_logów', index=False)
                
                # Arkusz Konwersja według statusów
                status_df = pd.DataFrame(data['status_conversion'])
                status_df.to_excel(writer, sheet_name='Konwersja_statusy', index=False)
                
                # Arkusz Ostatnie logi
                recent_df = pd.DataFrame(data['recent_logs'])
                recent_df.to_excel(writer, sheet_name='Ostatnie_logi', index=False)
                
            elif export_type == 'public_calc':
                # Dane kalkulatora publicznego
                for sheet_name, sheet_data in data.items():
                    df = pd.DataFrame(sheet_data)
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
        
        # KLUCZOWA ZMIANA: zapisz do BytesIO i ustaw pozycję
        output.seek(0)
        
        # Utwórz response z poprawnym content-type
        from flask import Response
        
        return Response(
            output.getvalue(),
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}.xlsx"',
                'Content-Length': str(len(output.getvalue()))
            }
        )
        
    except Exception as e:
        print(f"[export_to_excel] Błąd szczegółowy: {str(e)}")
        current_app.logger.error(f"Export Excel error: {str(e)}")
        return jsonify({'error': f'Błąd generowania Excel: {str(e)}'}), 500


def export_to_csv(data: dict, filename: str, export_type: str):
    """Eksportuje dane do pliku CSV (ZIP jeśli wiele arkuszy)"""
    
    # Jeśli tylko jeden arkusz danych, zwróć pojedynczy CSV
    if len(data) == 1:
        sheet_name, sheet_data = next(iter(data.items()))
        df = pd.DataFrame(sheet_data)
        
        output = BytesIO()
        df.to_csv(output, index=False, encoding='utf-8-sig')  # utf-8-sig dla polskich znaków
        output.seek(0)
        
        return send_file(
            output,
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'{filename}.csv'
        )
    
    # Jeśli wiele arkuszy, utwórz ZIP z wieloma plikami CSV
    else:
        zip_buffer = BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for sheet_name, sheet_data in data.items():
                df = pd.DataFrame(sheet_data)
                csv_buffer = BytesIO()
                df.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
                
                zip_file.writestr(f'{sheet_name}.csv', csv_buffer.getvalue())
        
        zip_buffer.seek(0)
        
        return send_file(
            zip_buffer,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f'{filename}.zip'
        )


def prepare_public_calc_export_data():
    """Przygotowuje dane kalkulatora publicznego do exportu"""
    
    # Podstawowe statystyki
    total_sessions = db.session.query(func.count(PublicSession.id)).scalar()
    avg_duration = db.session.query(func.avg(PublicSession.duration_ms)).scalar() or 0
    
    stats_data = [
        {'Metryka': 'Łączna liczba sesji', 'Wartość': total_sessions},
        {'Metryka': 'Średni czas sesji (ms)', 'Wartość': round(avg_duration, 2)},
        {'Metryka': 'Średni czas sesji (sek)', 'Wartość': round(avg_duration / 1000, 2)}
    ]
    
    # Warianty
    variants_raw = db.session.query(PublicSession.variant, func.count()).group_by(PublicSession.variant).all()
    variants_data = [{'Wariant': var[0] or 'Brak danych', 'Liczba_użyć': var[1]} for var in variants_raw]
    
    # Wykończenia
    finishings_raw = db.session.query(PublicSession.finishing, func.count()).group_by(PublicSession.finishing).all()
    finishings_data = [{'Wykończenie': fin[0] or 'Brak danych', 'Liczba_użyć': fin[1]} for fin in finishings_raw]
    
    # Kolory
    colors_raw = db.session.query(PublicSession.color, func.count()).group_by(PublicSession.color).all()
    colors_data = [{'Kolor': col[0] or 'Brak danych', 'Liczba_użyć': col[1]} for col in colors_raw]
    
    # Wymiary (parsowanie JSON)
    dims_raw = db.session.query(PublicSession.inputs).all()
    dims_counter = {}
    for row in dims_raw:
        try:
            data = json.loads(row[0])
            key = f"{data.get('length', '?')}x{data.get('width', '?')}x{data.get('thickness', '?')}"
            dims_counter[key] = dims_counter.get(key, 0) + 1
        except (json.JSONDecodeError, TypeError, AttributeError):
            continue
    
    dimensions_data = [{'Wymiary': dim, 'Liczba_użyć': count} for dim, count in sorted(dims_counter.items(), key=lambda x: x[1], reverse=True)]
    
    # Szczegółowe dane sesji (ostatnie 100)
    recent_sessions = db.session.query(PublicSession).order_by(PublicSession.timestamp.desc()).limit(100).all()
    
    sessions_data = []
    for session in recent_sessions:
        try:
            inputs_data = json.loads(session.inputs) if session.inputs else {}
        except:
            inputs_data = {}
            
        sessions_data.append({
            'ID': session.id,
            'Data_sesji': session.timestamp.strftime('%Y-%m-%d %H:%M:%S') if session.timestamp else '',
            'Wariant': session.variant or '',
            'Wykończenie': session.finishing or '',
            'Kolor': session.color or '',
            'Czas_trwania_ms': session.duration_ms or 0,
            'Długość': inputs_data.get('length', ''),
            'Szerokość': inputs_data.get('width', ''),
            'Grubość': inputs_data.get('thickness', ''),
            'IP_Address': session.ip_address or ''
        })
    
    return {
        'Statystyki_podstawowe': stats_data,
        'Warianty': variants_data,
        'Wykończenia': finishings_data,
        'Kolory': colors_data,
        'Wymiary': dimensions_data,
        'Ostatnie_sesje': sessions_data
    }


# =====================================
# ENDPOINTY POMOCNICZE
# =====================================

@analytics_bp.route("/debug_static")
def debug_static():
    """Debug endpoint dla statycznych plików"""
    static_path = os.path.join(current_app.root_path, "modules", "analytics", "static", "js", "public_analytics.js")
    exists = os.path.exists(static_path)
    return f"Ścieżka: {static_path} | Istnieje: {exists}"

@analytics_bp.route("/data")
def analytics_data():
    """Stary endpoint - przekierowanie do public_calc_data dla kompatybilności"""
    return public_calc_data()


# =====================================
# ENDPOINTY API DO FILTROWANIA I ZAAWANSOWANYCH ZAPYTAŃ
# =====================================

@analytics_bp.route("/api/sales/trends")
def api_sales_trends():
    """API endpoint dla trendów sprzedażowych z parametrami"""
    
    # Pobierz parametry z query string
    months = request.args.get('months', 12, type=int)
    
    if months < 1 or months > 36:
        return jsonify({'error': 'Parametr months musi być między 1 a 36'}), 400
    
    try:
        trends_data = AnalyticsQueries.get_sales_trends_data(months)
        return jsonify({
            'success': True,
            'trends': trends_data,
            'months': months
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@analytics_bp.route("/api/clients/top")
def api_top_clients():
    """API endpoint dla top klientów z parametrami"""
    
    limit = request.args.get('limit', 20, type=int)
    
    if limit < 1 or limit > 100:
        return jsonify({'error': 'Parametr limit musi być między 1 a 100'}), 400
    
    try:
        clients_data = AnalyticsQueries.get_clients_analytics_data(limit)
        return jsonify({
            'success': True,
            'clients': clients_data,
            'limit': limit
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@analytics_bp.route("/api/products/popular")
def api_popular_products():
    """API endpoint dla popularnych produktów z parametrami"""
    
    limit = request.args.get('limit', 10, type=int)
    
    if limit < 1 or limit > 50:
        return jsonify({'error': 'Parametr limit musi być między 1 a 50'}), 400
    
    try:
        products_data = AnalyticsQueries.get_popular_products_data(limit)
        return jsonify({
            'success': True,
            'products': products_data,
            'limit': limit
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500