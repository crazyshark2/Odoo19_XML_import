# -*- coding: utf-8 -*-

"""
Ürün Veri Zenginleştirme Modülü

Bu modül, ürün bilgilerini çeşitli web kaynaklarından otomatik olarak zenginleştirir:
- Türkiye: Hepsiburada, Trendyol, N11
- Global: Amazon, Google Shopping, UPC Database
- Özel: Kullanıcı tanımlı web siteleri

Kullanım:
1. Tek ürün: Ürün formunda "Zenginleştir" butonu
2. Toplu: Ürün listesinde seçili ürünler için aksiyon
3. Otomatik: Yeni ürün oluşturulduğunda (opsiyonel)
"""

import requests
import json
import re
import logging
import base64
from bs4 import BeautifulSoup
from urllib.parse import quote, urljoin
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# User-Agent for web requests
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'


class ProductEnrichmentSource(models.Model):
    """Ürün Zenginleştirme Kaynakları"""
    _name = 'product.enrichment.source'
    _description = 'Ürün Zenginleştirme Kaynağı'
    _order = 'sequence, name'

    name = fields.Char(string='Kaynak Adı', required=True)
    sequence = fields.Integer(string='Sıra', default=10)
    active = fields.Boolean(default=True)

    source_type = fields.Selection([
        ('hepsiburada', 'Hepsiburada'),
        ('trendyol', 'Trendyol'),
        ('n11', 'N11'),
        ('amazon', 'Amazon'),
        ('google', 'Google Shopping'),
        ('upc_database', 'UPC Database'),
        ('custom', 'Özel Web Sitesi'),
    ], string='Kaynak Tipi', required=True, default='custom')

    # Özel web sitesi ayarları
    base_url = fields.Char(string='Web Sitesi URL')
    search_url_pattern = fields.Char(
        string='Arama URL Deseni',
        help='Örnek: https://site.com/search?q={query}\n{query} arama terimi ile değiştirilir'
    )

    # Scraping kuralları (CSS Selectors)
    selector_name = fields.Char(string='Ürün Adı Selector', help='CSS Selector: örn. h1.product-title')
    selector_description = fields.Text(string='Açıklama Selector')
    selector_price = fields.Char(string='Fiyat Selector')
    selector_image = fields.Char(string='Görsel Selector')
    selector_brand = fields.Char(string='Marka Selector')
    selector_category = fields.Char(string='Kategori Selector')
    selector_sku = fields.Char(string='Stok Kodu Selector')
    selector_barcode = fields.Char(string='Barkod Selector')
    selector_specs = fields.Char(string='Özellikler Selector')
    selector_product_list = fields.Char(string='Ürün Listesi Selector', help='Arama sonuçlarındaki ürün kartları')
    selector_product_link = fields.Char(string='Ürün Linki Selector', help='Ürün detay sayfası linki')

    # API ayarları (opsiyonel)
    api_key = fields.Char(string='API Key')
    api_secret = fields.Char(string='API Secret')

    # İstatistikler
    last_used = fields.Datetime(string='Son Kullanım', readonly=True)
    success_count = fields.Integer(string='Başarılı', readonly=True)
    fail_count = fields.Integer(string='Başarısız', readonly=True)

    def _get_headers(self):
        """HTTP istekleri için header'lar"""
        return {
            'User-Agent': USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        }

    def search_product(self, query):
        """
        Ürün ara ve sonuçları döndür

        :param query: Arama terimi (barkod, ürün kodu veya isim)
        :return: list of dict with product data
        """
        self.ensure_one()

        if self.source_type == 'hepsiburada':
            return self._search_hepsiburada(query)
        elif self.source_type == 'trendyol':
            return self._search_trendyol(query)
        elif self.source_type == 'n11':
            return self._search_n11(query)
        elif self.source_type == 'amazon':
            return self._search_amazon(query)
        elif self.source_type == 'google':
            return self._search_google(query)
        elif self.source_type == 'upc_database':
            return self._search_upc_database(query)
        elif self.source_type == 'custom':
            return self._search_custom(query)

        return []

    def _search_hepsiburada(self, query):
        """Hepsiburada'da ürün ara"""
        results = []
        try:
            search_url = f"https://www.hepsiburada.com/ara?q={quote(query)}"
            response = requests.get(search_url, headers=self._get_headers(), timeout=15)

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')

                # Ürün kartlarını bul
                products = soup.select('li[class*="productListContent"]')[:5]

                for product in products:
                    try:
                        link_elem = product.select_one('a[href*="/p-"]')
                        if not link_elem:
                            continue

                        product_url = urljoin('https://www.hepsiburada.com', link_elem.get('href', ''))

                        # Detay sayfasını çek
                        detail = self._fetch_hepsiburada_detail(product_url)
                        if detail:
                            results.append(detail)
                    except Exception as e:
                        _logger.warning(f"Hepsiburada ürün parse hatası: {e}")

                self.write({'last_used': fields.Datetime.now(), 'success_count': self.success_count + 1})
        except Exception as e:
            _logger.error(f"Hepsiburada arama hatası: {e}")
            self.write({'fail_count': self.fail_count + 1})

        return results

    def _fetch_hepsiburada_detail(self, url):
        """Hepsiburada ürün detay sayfasını parse et"""
        try:
            response = requests.get(url, headers=self._get_headers(), timeout=15)
            if response.status_code != 200:
                return None

            soup = BeautifulSoup(response.text, 'html.parser')

            # JSON-LD'den veri çek
            script = soup.find('script', type='application/ld+json')
            if script:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, list):
                        data = data[0]

                    return {
                        'name': data.get('name', ''),
                        'description': data.get('description', ''),
                        'image_url': data.get('image', ''),
                        'brand': data.get('brand', {}).get('name', '') if isinstance(data.get('brand'), dict) else '',
                        'sku': data.get('sku', ''),
                        'price': data.get('offers', {}).get('price', 0) if isinstance(data.get('offers'), dict) else 0,
                        'source': 'hepsiburada',
                        'source_url': url,
                    }
                except json.JSONDecodeError:
                    pass

            # Fallback: HTML'den parse et
            name = soup.select_one('h1[class*="product-name"], h1#product-name')
            description = soup.select_one('div[class*="product-description"]')
            image = soup.select_one('img[class*="product-image"], img[data-src*="productimages"]')

            return {
                'name': name.get_text(strip=True) if name else '',
                'description': description.get_text(strip=True) if description else '',
                'image_url': image.get('src') or image.get('data-src', '') if image else '',
                'source': 'hepsiburada',
                'source_url': url,
            }
        except Exception as e:
            _logger.error(f"Hepsiburada detay hatası: {e}")
            return None

    def _search_trendyol(self, query):
        """Trendyol'da ürün ara"""
        results = []
        try:
            search_url = f"https://www.trendyol.com/sr?q={quote(query)}"
            response = requests.get(search_url, headers=self._get_headers(), timeout=15)

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')

                # Ürün kartlarını bul
                products = soup.select('div.p-card-wrppr')[:5]

                for product in products:
                    try:
                        link_elem = product.select_one('a')
                        if not link_elem:
                            continue

                        product_url = urljoin('https://www.trendyol.com', link_elem.get('href', ''))

                        # Detay sayfasını çek
                        detail = self._fetch_trendyol_detail(product_url)
                        if detail:
                            results.append(detail)
                    except Exception as e:
                        _logger.warning(f"Trendyol ürün parse hatası: {e}")

                self.write({'last_used': fields.Datetime.now(), 'success_count': self.success_count + 1})
        except Exception as e:
            _logger.error(f"Trendyol arama hatası: {e}")
            self.write({'fail_count': self.fail_count + 1})

        return results

    def _fetch_trendyol_detail(self, url):
        """Trendyol ürün detay sayfasını parse et"""
        try:
            response = requests.get(url, headers=self._get_headers(), timeout=15)
            if response.status_code != 200:
                return None

            soup = BeautifulSoup(response.text, 'html.parser')

            # JSON-LD'den veri çek
            script = soup.find('script', type='application/ld+json')
            if script:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, list):
                        data = data[0]

                    return {
                        'name': data.get('name', ''),
                        'description': data.get('description', ''),
                        'image_url': data.get('image', ''),
                        'brand': data.get('brand', {}).get('name', '') if isinstance(data.get('brand'), dict) else '',
                        'sku': data.get('sku', ''),
                        'price': data.get('offers', {}).get('price', 0) if isinstance(data.get('offers'), dict) else 0,
                        'source': 'trendyol',
                        'source_url': url,
                    }
                except json.JSONDecodeError:
                    pass

            return None
        except Exception as e:
            _logger.error(f"Trendyol detay hatası: {e}")
            return None

    def _search_n11(self, query):
        """N11'de ürün ara"""
        results = []
        try:
            search_url = f"https://www.n11.com/arama?q={quote(query)}"
            response = requests.get(search_url, headers=self._get_headers(), timeout=15)

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                products = soup.select('li.columnContent')[:5]

                for product in products:
                    try:
                        link_elem = product.select_one('a.plink')
                        name_elem = product.select_one('h3.productName')
                        img_elem = product.select_one('img')

                        if link_elem and name_elem:
                            results.append({
                                'name': name_elem.get_text(strip=True),
                                'image_url': img_elem.get('data-src', '') if img_elem else '',
                                'source': 'n11',
                                'source_url': link_elem.get('href', ''),
                            })
                    except Exception as e:
                        _logger.warning(f"N11 ürün parse hatası: {e}")

                self.write({'last_used': fields.Datetime.now(), 'success_count': self.success_count + 1})
        except Exception as e:
            _logger.error(f"N11 arama hatası: {e}")
            self.write({'fail_count': self.fail_count + 1})

        return results

    def _search_amazon(self, query):
        """Amazon'da ürün ara"""
        results = []
        try:
            # Amazon TR
            search_url = f"https://www.amazon.com.tr/s?k={quote(query)}"
            response = requests.get(search_url, headers=self._get_headers(), timeout=15)

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                products = soup.select('div[data-component-type="s-search-result"]')[:5]

                for product in products:
                    try:
                        title_elem = product.select_one('h2 a span')
                        link_elem = product.select_one('h2 a')
                        img_elem = product.select_one('img.s-image')

                        if title_elem and link_elem:
                            results.append({
                                'name': title_elem.get_text(strip=True),
                                'image_url': img_elem.get('src', '') if img_elem else '',
                                'source': 'amazon',
                                'source_url': urljoin('https://www.amazon.com.tr', link_elem.get('href', '')),
                            })
                    except Exception as e:
                        _logger.warning(f"Amazon ürün parse hatası: {e}")

                self.write({'last_used': fields.Datetime.now(), 'success_count': self.success_count + 1})
        except Exception as e:
            _logger.error(f"Amazon arama hatası: {e}")
            self.write({'fail_count': self.fail_count + 1})

        return results

    def _search_google(self, query):
        """Google Shopping'de ürün ara (SerpAPI ile)"""
        results = []
        # SerpAPI veya benzeri bir servis gerektirir
        # Şimdilik boş döndür, API key eklenince aktif edilir
        return results

    def _search_upc_database(self, query):
        """UPC Database'de barkod ara"""
        results = []
        try:
            # Sadece barkod ise ara
            if query.isdigit() and len(query) >= 8:
                api_url = f"https://api.upcitemdb.com/prod/trial/lookup?upc={query}"
                response = requests.get(api_url, headers={'Accept': 'application/json'}, timeout=10)

                if response.status_code == 200:
                    data = response.json()
                    items = data.get('items', [])

                    for item in items[:3]:
                        results.append({
                            'name': item.get('title', ''),
                            'description': item.get('description', ''),
                            'brand': item.get('brand', ''),
                            'category': item.get('category', ''),
                            'image_url': item.get('images', [''])[0] if item.get('images') else '',
                            'barcode': item.get('upc', ''),
                            'source': 'upc_database',
                        })

                    self.write({'last_used': fields.Datetime.now(), 'success_count': self.success_count + 1})
        except Exception as e:
            _logger.error(f"UPC Database arama hatası: {e}")
            self.write({'fail_count': self.fail_count + 1})

        return results

    def _search_custom(self, query):
        """Özel web sitesinde ürün ara"""
        results = []

        if not self.search_url_pattern:
            return results

        try:
            search_url = self.search_url_pattern.replace('{query}', quote(query))
            response = requests.get(search_url, headers=self._get_headers(), timeout=15)

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')

                # Ürün listesi selector varsa
                if self.selector_product_list:
                    products = soup.select(self.selector_product_list)[:10]

                    for product in products:
                        try:
                            data = self._extract_product_data(product, is_list=True)
                            if data.get('name') or data.get('source_url'):
                                # Detay sayfası varsa çek
                                if data.get('source_url') and self.selector_name:
                                    detail = self._fetch_custom_detail(data['source_url'])
                                    if detail:
                                        data.update(detail)
                                results.append(data)
                        except Exception as e:
                            _logger.warning(f"Özel site ürün parse hatası: {e}")
                else:
                    # Tek ürün sayfası
                    data = self._extract_product_data(soup, is_list=False)
                    if data.get('name'):
                        results.append(data)

                self.write({'last_used': fields.Datetime.now(), 'success_count': self.success_count + 1})
        except Exception as e:
            _logger.error(f"Özel site arama hatası: {e}")
            self.write({'fail_count': self.fail_count + 1})

        return results

    def _fetch_custom_detail(self, url):
        """Özel site ürün detay sayfasını parse et"""
        try:
            # Göreceli URL'yi absolute yap
            if not url.startswith('http'):
                url = urljoin(self.base_url, url)

            response = requests.get(url, headers=self._get_headers(), timeout=15)
            if response.status_code != 200:
                return None

            soup = BeautifulSoup(response.text, 'html.parser')
            return self._extract_product_data(soup, is_list=False)
        except Exception as e:
            _logger.error(f"Özel site detay hatası: {e}")
            return None

    def _extract_product_data(self, element, is_list=False):
        """HTML element'ten ürün verilerini çıkar"""
        data = {
            'source': 'custom',
            'source_url': '',
        }

        # İsim
        if self.selector_name:
            elem = element.select_one(self.selector_name)
            if elem:
                data['name'] = elem.get_text(strip=True)

        # Açıklama
        if self.selector_description:
            elem = element.select_one(self.selector_description)
            if elem:
                data['description'] = elem.get_text(strip=True)

        # Fiyat
        if self.selector_price:
            elem = element.select_one(self.selector_price)
            if elem:
                price_text = elem.get_text(strip=True)
                # Fiyatı parse et
                price_match = re.search(r'[\d.,]+', price_text.replace('.', '').replace(',', '.'))
                if price_match:
                    try:
                        data['price'] = float(price_match.group())
                    except ValueError:
                        pass

        # Görsel
        if self.selector_image:
            elem = element.select_one(self.selector_image)
            if elem:
                data['image_url'] = elem.get('src') or elem.get('data-src', '')
                if data['image_url'] and not data['image_url'].startswith('http'):
                    data['image_url'] = urljoin(self.base_url, data['image_url'])

        # Marka
        if self.selector_brand:
            elem = element.select_one(self.selector_brand)
            if elem:
                data['brand'] = elem.get_text(strip=True)

        # Kategori
        if self.selector_category:
            elem = element.select_one(self.selector_category)
            if elem:
                data['category'] = elem.get_text(strip=True)

        # Stok Kodu
        if self.selector_sku:
            elem = element.select_one(self.selector_sku)
            if elem:
                data['sku'] = elem.get_text(strip=True)

        # Barkod
        if self.selector_barcode:
            elem = element.select_one(self.selector_barcode)
            if elem:
                data['barcode'] = elem.get_text(strip=True)

        # Ürün linki (liste görünümünde)
        if is_list and self.selector_product_link:
            elem = element.select_one(self.selector_product_link)
            if elem:
                data['source_url'] = elem.get('href', '')

        return data

    def scrape_all_products(self):
        """Tüm ürünleri siteden çek ve Odoo'ya aktar"""
        self.ensure_one()

        if self.source_type != 'custom':
            raise UserError(_('Bu özellik sadece özel web siteleri için kullanılabilir.'))

        if not self.base_url:
            raise UserError(_('Web sitesi URL\'i belirtilmemiş.'))

        # Wizard aç
        return {
            'name': _('Web Sitesi Ürün Aktarımı'),
            'type': 'ir.actions.act_window',
            'res_model': 'product.enrichment.import.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_source_id': self.id,
            }
        }


class ProductEnrichmentLog(models.Model):
    """Ürün Zenginleştirme Logları"""
    _name = 'product.enrichment.log'
    _description = 'Ürün Zenginleştirme Log'
    _order = 'create_date desc'

    product_id = fields.Many2one('product.template', string='Ürün', ondelete='cascade')
    source_id = fields.Many2one('product.enrichment.source', string='Kaynak')

    search_query = fields.Char(string='Arama Terimi')
    status = fields.Selection([
        ('success', 'Başarılı'),
        ('partial', 'Kısmi'),
        ('not_found', 'Bulunamadı'),
        ('error', 'Hata'),
    ], string='Durum')

    fields_updated = fields.Text(string='Güncellenen Alanlar')
    source_url = fields.Char(string='Kaynak URL')
    error_message = fields.Text(string='Hata Mesajı')

    raw_data = fields.Text(string='Ham Veri')


class ProductTemplateEnrichment(models.Model):
    """Product Template'e Zenginleştirme Özellikleri Ekle"""
    _inherit = 'product.template'

    enrichment_log_ids = fields.One2many(
        'product.enrichment.log',
        'product_id',
        string='Zenginleştirme Geçmişi',
    )

    last_enrichment_date = fields.Datetime(
        string='Son Zenginleştirme',
        readonly=True,
    )

    enrichment_source = fields.Char(
        string='Zenginleştirme Kaynağı',
        readonly=True,
    )

    auto_enrich = fields.Boolean(
        string='Otomatik Zenginleştir',
        default=False,
        help='Yeni oluşturulduğunda otomatik zenginleştir',
    )

    def action_enrich_product(self):
        """Ürünü zenginleştir butonu"""
        self.ensure_one()

        return {
            'name': _('Ürün Zenginleştir'),
            'type': 'ir.actions.act_window',
            'res_model': 'product.enrichment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_product_id': self.id,
                'default_search_query': self.barcode or self.default_code or self.name,
            }
        }

    def enrich_from_web(self, query=None, sources=None):
        """
        Web'den ürün bilgilerini zenginleştir

        :param query: Arama terimi (varsayılan: barkod veya ürün kodu)
        :param sources: Kullanılacak kaynaklar (varsayılan: tüm aktif kaynaklar)
        :return: dict with enrichment results
        """
        self.ensure_one()

        if not query:
            query = self.barcode or self.default_code or self.name

        if not query:
            return {'status': 'error', 'message': 'Arama terimi bulunamadı'}

        if not sources:
            sources = self.env['product.enrichment.source'].search([('active', '=', True)])

        results = []
        best_result = None

        # Önce Türkiye kaynakları, sonra global
        tr_sources = sources.filtered(lambda s: s.source_type in ['hepsiburada', 'trendyol', 'n11'])
        global_sources = sources.filtered(lambda s: s.source_type in ['amazon', 'google', 'upc_database'])
        custom_sources = sources.filtered(lambda s: s.source_type == 'custom')

        # Sırayla ara
        for source in tr_sources + global_sources + custom_sources:
            try:
                source_results = source.search_product(query)
                if source_results:
                    results.extend(source_results)
                    if not best_result:
                        best_result = source_results[0]
                        best_result['source_name'] = source.name
            except Exception as e:
                _logger.error(f"Kaynak hatası ({source.name}): {e}")

        if not best_result:
            # Log kaydet
            self.env['product.enrichment.log'].create({
                'product_id': self.id,
                'search_query': query,
                'status': 'not_found',
            })
            return {'status': 'not_found', 'message': 'Ürün bulunamadı'}

        # Ürünü güncelle
        updated_fields = []
        update_vals = {}

        # İsim (sadece boşsa)
        if not self.name and best_result.get('name'):
            update_vals['name'] = best_result['name']
            updated_fields.append('name')

        # Açıklama
        if not self.description_sale and best_result.get('description'):
            update_vals['description_sale'] = best_result['description']
            updated_fields.append('description_sale')

        # Görsel
        if not self.image_1920 and best_result.get('image_url'):
            try:
                img_response = requests.get(best_result['image_url'], timeout=10)
                if img_response.status_code == 200:
                    update_vals['image_1920'] = base64.b64encode(img_response.content)
                    updated_fields.append('image_1920')
            except Exception as e:
                _logger.warning(f"Görsel indirme hatası: {e}")

        # Görsel URL (yedek olarak sakla)
        if best_result.get('image_url') and not self.xml_image_url:
            update_vals['xml_image_url'] = best_result['image_url']
            updated_fields.append('xml_image_url')

        if update_vals:
            update_vals['last_enrichment_date'] = fields.Datetime.now()
            update_vals['enrichment_source'] = best_result.get('source_name', best_result.get('source', ''))
            self.write(update_vals)

        # Log kaydet
        self.env['product.enrichment.log'].create({
            'product_id': self.id,
            'search_query': query,
            'status': 'success' if updated_fields else 'partial',
            'fields_updated': ', '.join(updated_fields) if updated_fields else 'Hiçbiri',
            'source_url': best_result.get('source_url', ''),
            'raw_data': json.dumps(best_result, ensure_ascii=False),
        })

        return {
            'status': 'success',
            'updated_fields': updated_fields,
            'source': best_result.get('source', ''),
            'all_results': results,
        }

    @api.model_create_multi
    def create(self, vals_list):
        """Yeni ürün oluşturulduğunda otomatik zenginleştir"""
        records = super().create(vals_list)

        # Otomatik zenginleştirme aktif mi kontrol et
        auto_enrich_config = self.env['ir.config_parameter'].sudo().get_param(
            'product_enrichment.auto_enrich_new', 'False'
        )

        if auto_enrich_config == 'True':
            for record in records:
                if record.barcode or record.default_code:
                    try:
                        record.with_delay().enrich_from_web()  # Queue job ile
                    except Exception:
                        # Queue job yoksa direkt çalıştır
                        try:
                            record.enrich_from_web()
                        except Exception as e:
                            _logger.warning(f"Otomatik zenginleştirme hatası: {e}")

        return records
