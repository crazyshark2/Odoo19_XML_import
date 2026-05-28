# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import logging
import re
import json
import html
import base64
import time
from difflib import SequenceMatcher
from io import BytesIO
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_logger = logging.getLogger(__name__)


class XmlProductSource(models.Model):
    """XML Ürün Kaynağı - Dropshipping Tedarikçi Feed'i"""
    _name = 'xml.product.source'
    _description = 'XML Ürün Kaynağı'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, name'

    name = fields.Char(
        string='Kaynak Adı',
        required=True,
        tracking=True,
        help='Tedarikçi veya feed adı',
    )
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)

    # Tedarikçi Bilgileri
    supplier_id = fields.Many2one(
        'res.partner',
        string='Tedarikçi',
        domain=[('supplier_rank', '>', 0)],
        help='Bu XML kaynağına bağlı tedarikçi',
    )

    # XML Ayarları
    xml_url = fields.Char(
        string='XML URL',
        required=True,
        tracking=True,
        help='Ürün feed URL adresi',
    )
    xml_username = fields.Char(
        string='Kullanıcı Adı',
        help='HTTP Basic Auth kullanıcı adı (opsiyonel)',
    )
    xml_password = fields.Char(
        string='Şifre',
        help='HTTP Basic Auth şifresi (opsiyonel)',
    )
    xml_token = fields.Char(
        string='API Token',
        help='Token tabanlı servisler için opsiyonel API anahtarı',
    )

    # Index Grup / Netex ayrı feed URL'leri
    xml_stock_url = fields.Char(
        string='Stok XML URL',
        help='Ayrı stok feed URL (Index Grup/Netex için)',
    )
    xml_price_url = fields.Char(
        string='Fiyat XML URL',
        help='Ayrı fiyat feed URL (Index Grup/Netex için)',
    )

    # XML Yapısı
    xml_template = fields.Selection([
        ('tsoft', 'T-Soft'),
        ('ticimax', 'Ticimax'),
        ('ideasoft', 'IdeaSoft'),
        ('akinsoft', 'Akinsoft (Wolvox)'),
        ('eminonu', 'Eminonu XML'),
        ('google_rss', 'Google RSS / Merchant Feed'),
        ('opencart', 'OpenCart'),
        ('woocommerce', 'WooCommerce'),
        ('woocommerce_api', 'WooCommerce API'),
        ('tesan', 'Tesan SOAP'),
        ('soap', 'Genel SOAP'),
        ('tesan_soap', 'Tesan SOAP (legacy)'),
        ('prestashop', 'PrestaShop'),
        ('shopify', 'Shopify'),
        ('magento', 'Magento'),
        ('google', 'Google Shopping'),
        ('n11', 'N11'),
        ('trendyol', 'Trendyol'),
        ('hepsiburada', 'Hepsiburada'),
        ('cimri', 'Cimri'),
        ('akakce', 'Akakçe'),
        ('indexgrup', 'Index Grup'),
        ('netex', 'Netex'),
        ('custom', 'Özel (Custom)'),
    ], string='XML Şablonu', default='custom', required=True)

    root_element = fields.Char(
        string='Kök Element (XPath)',
        default='//Product',
        help='Ürün elementlerinin XPath yolu. Örnek: //Products/Product veya //item',
    )

    # Durum
    state = fields.Selection([
        ('draft', 'Taslak'),
        ('active', 'Aktif'),
        ('error', 'Hata'),
        ('paused', 'Duraklatıldı'),
    ], string='Durum', default='draft', tracking=True)

    last_sync = fields.Datetime(
        string='Son Senkronizasyon',
        readonly=True,
    )
    last_error = fields.Text(
        string='Son Hata',
        readonly=True,
    )

    # İstatistikler
    product_count = fields.Integer(
        string='Ürün Sayısı',
        compute='_compute_counts',
    )
    log_count = fields.Integer(
        string='Log Sayısı',
        compute='_compute_counts',
    )

    # İlişkiler
    field_mapping_ids = fields.One2many(
        'xml.field.mapping',
        'source_id',
        string='Alan Eşleştirmeleri',
    )
    import_log_ids = fields.One2many(
        'xml.import.log',
        'source_id',
        string='İçe Aktarım Logları',
    )

    # Dropshipping Fiyatlandırma
    price_markup_type = fields.Selection([
        ('percent', 'Yüzde (%)'),
        ('fixed', 'Sabit Tutar'),
        ('both', 'Her İkisi'),
    ], string='Kar Tipi', default='percent')

    price_markup_percent = fields.Float(
        string='Kar Marjı (%)',
        default=30.0,
        help='Tedarikçi fiyatına eklenecek yüzde',
    )
    price_markup_fixed = fields.Float(
        string='Sabit Kar',
        default=0.0,
        help='Tedarikçi fiyatına eklenecek sabit tutar',
    )
    price_round = fields.Boolean(
        string='Fiyatı Yuvarla',
        default=True,
        help='Satış fiyatını yuvarla (örn: 149.99)',
    )
    price_round_method = fields.Selection([
        ('99', '.99 ile bitir'),
        ('90', '.90 ile bitir'),
        ('00', 'Tam sayı'),
        ('none', 'Yuvarlamadan'),
    ], string='Yuvarlama', default='99')

    min_price = fields.Float(
        string='Minimum Fiyat',
        help='Bu fiyatın altındaki ürünleri atla',
    )
    max_price = fields.Float(
        string='Maksimum Fiyat',
        help='Bu fiyatın üstündeki ürünleri atla',
    )
    min_stock = fields.Integer(
        string='Minimum Stok',
        default=0,  # ⚠️ 0 yapıldı - Dropshipping ürünler stok kontrolü yapmaz
        help='Bu stok miktarının altındaki ürünleri atla (0 = Tüm ürünleri al)',
    )

    # Senkronizasyon Ayarları
    auto_sync = fields.Boolean(
        string='Otomatik Senkronizasyon',
        default=True,
    )
    sync_interval = fields.Integer(
        string='Senkronizasyon Aralığı (saat)',
        default=6,
    )
    next_sync = fields.Datetime(
        string='Sonraki Senkronizasyon',
        compute='_compute_next_sync',
    )

    # İçe Aktarım Seçenekleri
    create_new_products = fields.Boolean(
        string='Yeni Ürün Oluştur',
        default=True,
        help='XML\'de olup Odoo\'da olmayan ürünler için stok kartı oluştur',
    )
    update_existing = fields.Boolean(
        string='Mevcut Ürünleri Güncelle',
        default=True,
        help='Odoo\'da mevcut ürünlerin bilgilerini güncelle',
    )
    update_price = fields.Boolean(
        string='Fiyat Güncelle',
        default=True,
    )
    update_stock = fields.Boolean(
        string='Stok Güncelle',
        default=True,
    )
    update_images = fields.Boolean(
        string='Görselleri Güncelle',
        default=True,
    )
    download_images = fields.Boolean(
        string='Görselleri İndir',
        default=False,
        help='Görselleri URL\'den indirip Odoo\'ya kaydet (kapalıysa sadece URL linki ile gösterilir)',
    )
    update_description = fields.Boolean(
        string='Açıklamaları Güncelle',
        default=True,
        help='Ürün açıklamalarını güncelle',
    )

    # Stok Sıfır Politikası
    deactivate_zero_stock = fields.Boolean(
        string='Stok 0 Olunca Satışa Kapat',
        default=False,  # ⚠️ KAPATILDI - Dropshipping ürünler için stok kontrolü yapılmaz
        help='Stok miktarı 0 olan ürünleri satışa kapat (sale_ok = False)',
    )
    delete_unsold_zero_stock = fields.Boolean(
        string='Satışı Olmayan 0 Stokları Sil',
        default=False,  # ⚠️ KAPATILDI - Hiçbir zaman ürün silmeyecek
        help='Stok 0 olduğunda ve hiç satışı olmayan ürünleri sistemden sil',
    )

    # SOAP Servisi Ayarları
    soap_namespace = fields.Char(
        string='SOAP Namespace',
        default='http://tempuri.org/',
        help='SOAP Header ve Body için xmlns ad alanı',
    )
    soap_product_element = fields.Char(
        string='Ürün Elementi',
        default='ProductList',
        help='SOAP yanıtındaki ürün XML element adı',
    )
    soap_extra_body = fields.Char(
        string='Ek Body',
        default='<_departman>0</_departman>',
        help='Ürün metodu çağrılırken gönderilecek ek parametre XML',
    )
    soap_method_products = fields.Char(
        string='Ürün Metodu',
        default='GetProductLists',
    )
    soap_method_prices = fields.Char(
        string='Fiyat Metodu',
        default='GetStockPrices',
    )
    soap_method_stock = fields.Char(
        string='Stok Metodu',
        default='GetWareHouseStocks',
    )
    soap_method_images = fields.Char(
        string='Görsel Metodu',
        default='GetProductImages',
    )
    soap_method_features = fields.Char(
        string='Özellik Metodu',
        default='GetProductFeatures',
    )
    soap_method_categories = fields.Char(
        string='Kategori Metodu',
        default='GetProductCategories',
    )

    # Varyant Ayarları
    create_variants = fields.Boolean(
        string='Varyant Oluştur',
        default=True,
        help='Aynı SKU farklı barkod = Varyant olarak aç',
    )
    variant_from_parentheses = fields.Boolean(
        string='Parantezden Varyant',
        default=True,
        help='Ürün adındaki parantez içeriğini varyant olarak kullan. Örn: "BOLD SPEAKER (KIRMIZI)" → Ana ürün: BOLD SPEAKER, Varyant: KIRMIZI',
    )
    variant_attribute_name = fields.Char(
        string='Varyant Özellik Adı',
        default='Renk',
        help='Varyantlar için kullanılacak özellik adı (Renk, Beden, vb.)',
    )

    # Eşleştirme Önceliği (Yeni Sıralama)
    match_by_sku_prefix = fields.Boolean(
        string='SKU Prefix ile Eşleştir',
        default=True,
        help='Ürün kodunun ilk kelimesi ile eşleştir (öncelik 1)',
    )
    match_by_barcode = fields.Boolean(
        string='Barkod ile Eşleştir',
        default=True,
        help='Barkod ile eşleştir (öncelik 2)',
    )
    match_by_sku = fields.Boolean(
        string='Ürün Kodu ile Eşleştir (Tam)',
        default=True,
        help='Tam ürün kodu ile eşleştir',
    )
    match_by_description = fields.Boolean(
        string='Açıklama ile Eşleştir',
        default=True,
        help='Açıklama benzerliği veya açıklamada ürün kodu varsa eşleştir (öncelik 3)',
    )
    match_by_name = fields.Boolean(
        string='İsim ile Eşleştir',
        default=True,
    )
    name_match_ratio = fields.Integer(
        string='İsim Benzerlik Oranı (%)',
        default=80,
        help='İsim eşleştirmesi için minimum benzerlik oranı',
    )
    description_match_ratio = fields.Integer(
        string='Açıklama Benzerlik Oranı (%)',
        default=50,
        help='Açıklama eşleştirmesi için minimum benzerlik oranı',
    )
    update_only_if_value = fields.Boolean(
        string='Sadece Değer Varsa Güncelle',
        default=True,
        help='Fiyat/stok boşsa mevcut değeri değiştirme',
    )

    # Kategori Ayarları
    update_category = fields.Boolean(
        string='Kategori Güncelle',
        default=True,
        help='Mevcut ürünlerin kategorisini XML\'den güncelle',
    )
    auto_create_category = fields.Boolean(
        string='Kategori Otomatik Oluştur',
        default=True,
        help='XML\'de gelen kategori Odoo\'da yoksa otomatik oluştur',
    )
    category_separator = fields.Char(
        string='Kategori Ayracı',
        default=' > ',
        help='Kategori yolu için ayraç (örn: "Ana Kategori > Alt Kategori")',
    )
    category_mapping_ids = fields.One2many(
        'xml.category.mapping',
        'source_id',
        string='Kategori Eşleştirmeleri',
        help='XML kategorilerini Odoo kategorilerine eşleştir',
    )
    variant_mapping_ids = fields.One2many(
        'xml.variant.mapping',
        'source_id',
        string='Varyant Özellik Eşleştirmeleri',
        help='XML varyant değerlerini Odoo attribute değerlerine eşleştir',
    )
    default_category_id = fields.Many2one(
        'product.category',
        string='Varsayılan Kategori',
        help='XML\'de kategori yoksa veya bulunamazsa kullanılacak kategori',
    )
    default_product_type = fields.Selection([
        ('consu', 'Stoklanan Ürün'),  # Odoo 19: 'product' -> 'consu'
        ('service', 'Hizmet'),
    ], string='Varsayılan Ürün Tipi', default='consu')

    # ══════════════════════════════════════════════════════════════════════════
    # COMPUTE METHODS
    # ══════════════════════════════════════════════════════════════════════════

    def _compute_counts(self):
        for record in self:
            record.product_count = self.env['product.template'].search_count([
                ('xml_source_id', '=', record.id)
            ])
            record.log_count = self.env['xml.import.log'].search_count([
                ('source_id', '=', record.id)
            ])

    @api.depends('last_sync', 'auto_sync', 'sync_interval')
    def _compute_next_sync(self):
        for record in self:
            if record.last_sync and record.auto_sync:
                record.next_sync = record.last_sync + timedelta(hours=record.sync_interval)
            else:
                record.next_sync = False

    # ══════════════════════════════════════════════════════════════════════════
    # TEMPLATE METHODS
    # ══════════════════════════════════════════════════════════════════════════

    @api.onchange('xml_template')
    def _onchange_xml_template(self):
        """Şablon değiştiğinde varsayılan mapping'leri ayarla"""
        template_roots = {
            'tsoft': 'product',
            'ticimax': '//Products/Product',
            'ideasoft': '//ProductList/Product',
            'akinsoft': '//urun',
            'eminonu': '//products/product',
            'google_rss': '//rss/channel/item',
            'opencart': '//products/product',
            'woocommerce': '//rss/channel/item',
            'woocommerce_api': '//products/product',
            'tesan': '//Products/Product',
            'tesan_soap': '//Products/Product',
            'prestashop': '//products/product',
            'shopify': '//products/product',
            'magento': '//products/product',
            'google': '//feed/entry',
            'n11': '//Products/Product',
            'trendyol': '//items/item',
            'hepsiburada': '//products/product',
            'cimri': '//products/product',
            'akakce': '//Products/Product',
            'indexgrup': './/URUN',
            'netex': './/URUN',
        }
        if self.xml_template and self.xml_template != 'custom':
            self.root_element = template_roots.get(self.xml_template, '//Product')

    def action_load_template_mappings(self):
        """Şablona göre varsayılan alan eşleştirmelerini yükle"""
        self.ensure_one()

        # Mevcut mapping'leri sil
        self.field_mapping_ids.unlink()

        # Şablona göre mapping'ler
        templates = {
            'tsoft': {
                'sku': 'ws_code',
                'barcode': 'barcode',
                'name': 'name',
                'description': 'detail',
                'price': 'price_special',
                'cost_price': 'price',
                'stock': 'stock',
                'category': 'category',
                'brand': 'brand',
                'image': 'picture1',
                'weight': 'weight',
                'deci': 'deci',
                'model': 'model',
                'currency': 'currency',
                'tax': 'tax',
            },
            'ticimax': {
                'sku': 'ProductCode',
                'barcode': 'Barcode',
                'name': 'ProductName',
                'description': 'Description',
                'price': 'Price1',
                'cost_price': 'BuyingPrice',
                'stock': 'Stock',
                'category': 'Category/CategoryName',
                'brand': 'Brand',
                'image': 'Images/Image/Path',
                'weight': 'Weight',
                'deci': 'Deci',
            },
            'ideasoft': {
                'sku': 'Code',
                'barcode': 'Barcode',
                'name': 'Name',
                'description': 'Details',
                'price': 'Price',
                'cost_price': 'CostPrice',
                'stock': 'Quantity',
                'category': 'Categories/Category',
                'brand': 'Brand',
                'image': 'Images/Image/Url',
                'weight': 'Weight',
            },
            'akinsoft': {
                'sku': 'STOK_KODU',
                'barcode': 'BARKODU',
                'name': 'STOK_ADI',
                'description': 'DETAY',
                'category': 'KATEGORI',
                'brand': 'MARKA',
                'image': 'GORSEL1',
                'image2': 'GORSEL2',
                'image3': 'GORSEL3',
                'image4': 'GORSEL4',
                'extra1': 'ALTKATEGORI',
            },
            'eminonu': {
                'sku': 'Urun_Kodu',
                'barcode': 'Urun_Kodu',
                'name': 'Urun_Adi',
                'description': 'Aciklama',
                'price': 'Fiyat',
                'cost_price': 'Fiyat',
                'stock': 'Stok',
                'category': 'Kategori',
                'brand': 'Marka',
                'image': 'resim1',
                'image2': 'resim2',
                'image3': 'resim3',
                'image4': 'resim4',
            },
            'google_rss': {
                'sku': 'model_number',
                'barcode': 'barcode',
                'name': 'title',
                'description': 'description',
                'price': 'price',
                'cost_price': 'price',
                'stock': 'quantity',
                'category': 'category',
                'brand': 'brand',
                'image': 'image_link',
                'image2': 'additional_image_link1',
                'image3': 'additional_image_link2',
                'image4': 'additional_image_link3',
                'extra1': 'product_type',
            },
            'opencart': {
                'sku': 'model',
                'barcode': 'ean',
                'name': 'name',
                'description': 'description',
                'price': 'price',
                'stock': 'quantity',
                'category': 'category',
                'image': 'image',
                'weight': 'weight',
            },
            'woocommerce': {
                'sku': 'g:id',
                'barcode': 'g:gtin',
                'name': 'title',
                'description': 'description',
                'price': 'g:price',
                'stock': 'g:availability',
                'category': 'g:product_type',
                'brand': 'g:brand',
                'image': 'g:image_link',
            },
            'woocommerce_api': {
                'sku': 'SKU',
                'barcode': 'Barcode',
                'name': 'Name',
                'description': 'Description',
                'price': 'Price',
                'cost_price': 'RegularPrice',
                'stock': 'Stock',
                'category': 'Category',
                'brand': 'Brand',
                'image': 'Image',
                'images': 'Images/Image',
                'currency': 'Currency',
                'extra1': 'Attributes',
            },
            'tesan': {
                'sku': 'SKU',
                'barcode': 'Barcode',
                'name': 'Name',
                'description': 'Description',
                'price': 'Price',
                'cost_price': 'CostPrice',
                'stock': 'Stock',
                'category': 'Category',
                'brand': 'Brand',
                'image': 'Image',
                'images': 'Images/Image',
                'currency': 'Currency',
                'extra1': 'SubCategory',
            },
            'tesan_soap': {
                'sku': 'SKU',
                'barcode': 'Barcode',
                'name': 'Name',
                'description': 'Description',
                'price': 'Price',
                'cost_price': 'CostPrice',
                'stock': 'Stock',
                'category': 'Category',
                'brand': 'Brand',
                'image': 'Image',
                'images': 'Images/Image',
                'currency': 'Currency',
                'extra1': 'SubCategory',
            },
            'prestashop': {
                'sku': 'reference',
                'barcode': 'ean13',
                'name': 'name',
                'description': 'description',
                'price': 'price',
                'stock': 'quantity',
                'category': 'category',
                'image': 'image',
                'weight': 'weight',
            },
            'shopify': {
                'sku': 'sku',
                'barcode': 'barcode',
                'name': 'title',
                'description': 'body_html',
                'price': 'price',
                'stock': 'inventory_quantity',
                'category': 'product_type',
                'brand': 'vendor',
                'image': 'image/src',
            },
            'magento': {
                'sku': 'sku',
                'barcode': 'barcode',
                'name': 'name',
                'description': 'description',
                'price': 'price',
                'stock': 'qty',
                'category': 'category',
                'image': 'image',
                'weight': 'weight',
            },
            'google': {
                'sku': 'g:id',
                'barcode': 'g:gtin',
                'name': 'title',
                'description': 'content',
                'price': 'g:price',
                'category': 'g:google_product_category',
                'brand': 'g:brand',
                'image': 'g:image_link',
            },
            'n11': {
                'sku': 'productSellerCode',
                'barcode': 'barcode',
                'name': 'title',
                'description': 'description',
                'price': 'price',
                'stock': 'quantity',
                'category': 'category/name',
                'image': 'images/image/url',
            },
            'trendyol': {
                'sku': 'stockCode',
                'barcode': 'barcode',
                'name': 'title',
                'description': 'description',
                'price': 'salePrice',
                'cost_price': 'listPrice',
                'stock': 'quantity',
                'category': 'categoryName',
                'brand': 'brand',
                'image': 'images/url',
            },
            'hepsiburada': {
                'sku': 'merchantSku',
                'barcode': 'barcode',
                'name': 'productName',
                'description': 'description',
                'price': 'price',
                'stock': 'availableStock',
                'category': 'categoryName',
                'image': 'image',
            },
            'cimri': {
                'sku': 'merchantItemId',
                'barcode': 'gtin',
                'name': 'name',
                'description': 'description',
                'price': 'price',
                'stock': 'availability',
                'category': 'category',
                'brand': 'brand',
                'image': 'imageUrl',
            },
            'akakce': {
                'sku': 'Code',
                'barcode': 'Barcode',
                'name': 'Name',
                'price': 'Price',
                'stock': 'Stock',
                'category': 'Category',
                'brand': 'Brand',
                'image': 'Image',
            },
            'indexgrup': {
                'sku': '@GLOBALKOD',
                'barcode': '@BARCODE',
                'name': '@AD',
                'brand': '@MARKA',
                'category': '@_KATEGORI',
                'extra1': '@_GRUP',
                'tax': 'VERGI',
                'image': 'RESIM',
            },
            'netex': {
                'sku': '@GLOBALKOD',
                'barcode': '@BARCODE',
                'name': '@AD',
                'brand': '@MARKA',
                'category': '@_KATEGORI',
                'extra1': '@_GRUP',
                'tax': 'VERGI',
                'image': 'RESIM',
            },
        }

        mapping_data = templates.get(self.xml_template, {})

        for odoo_field, xml_path in mapping_data.items():
            self.env['xml.field.mapping'].create({
                'source_id': self.id,
                'odoo_field': odoo_field,
                'xml_path': xml_path,
            })

        category_count = 0
        auto_matched_count = 0
        category_warning = None
        try:
            category_count, auto_matched_count = self._sync_template_category_mappings(mapping_data)
        except UserError as exc:
            category_warning = str(exc)
        except Exception as exc:
            _logger.warning("Şablon kategori eşlemeleri yüklenemedi (%s): %s", self.name, exc)
            category_warning = str(exc)

        message = _('%s alan eşleştirmesi yüklendi.') % len(mapping_data)
        if category_count:
            message += ' ' + _('%s XML kategorisi kategori eşleme sekmesine eklendi.') % category_count
        if auto_matched_count:
            message += ' ' + _('%s kategori otomatik eşleştirildi.') % auto_matched_count
        elif category_warning:
            message += ' ' + _('Kategori eşlemeleri yüklenemedi: %s') % category_warning

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Başarılı'),
                'message': message,
                'type': 'warning' if category_warning else 'success',
                'sticky': bool(category_warning),
                'next': {
                    'type': 'ir.actions.act_window',
                    'name': _('XML Kaynağı'),
                    'res_model': 'xml.product.source',
                    'res_id': self.id,
                    'view_mode': 'form',
                    'views': [(False, 'form')],
                    'target': 'current',
                },
            }
        }

    def _normalize_category_name(self, value):
        """Kategori adlarını kaba eşleştirme için normalize et."""
        value = (value or '').strip()
        if not value:
            return ''
        translate_map = str.maketrans({
            'Ç': 'c', 'ç': 'c',
            'Ğ': 'g', 'ğ': 'g',
            'I': 'i', 'İ': 'i', 'ı': 'i',
            'Ö': 'o', 'ö': 'o',
            'Ş': 's', 'ş': 's',
            'Ü': 'u', 'ü': 'u',
        })
        value = value.translate(translate_map).lower()
        value = re.sub(r'[^a-z0-9]+', ' ', value)
        return ' '.join(value.split())

    def _split_xml_category_path(self, xml_category):
        """XML kategori yolunu segmentlere ayır."""
        xml_category = (xml_category or '').strip()
        if not xml_category:
            return []

        separators = []
        if self.category_separator:
            separators.append(re.escape(self.category_separator))
        separators.extend([r'\s*>\s*', r'\s*/\s*', r'\s*\|\s*'])
        parts = re.split('|'.join(dict.fromkeys(separators)), xml_category)
        return [part.strip() for part in parts if part and part.strip()]

    def _normalized_category_key(self, category_name):
        """Kategori adını karşılaştırma için normalize eder."""
        return self._normalize_category_name(category_name)

    def _public_category_path_from_xml(self, xml_category):
        """TV Shop kurallarına göre XML kategorisini e-ticaret kategorisi yoluna çevir."""
        parts = self._split_xml_category_path(xml_category)
        if not parts:
            return []

        def _normalize_label(label):
            return self._normalized_category_key(label or '')

        if len(parts) > 3:
            parts = parts[:3]

        root_map = {
            _normalize_label('Ev ve Yaşam'): 'Ev & Yaşam',
            _normalize_label('Evcil Hayvan Ürünleri'): 'Evcil Hayvan Ürünleri',
            _normalize_label('Kozmetik'): 'Kozmetik & Kişisel Bakım',
            _normalize_label('Oto Aksesuar Ürünleri'): 'Oto Aksesuarları',
            _normalize_label('Outdoor Ürünleri'): 'Outdoor & Kamp',
            _normalize_label('Hırdavat Malzemeleri'): 'Hırdavat',
            _normalize_label('Oyuncak & Kırtasiye'): 'Oyuncak & Kırtasiye',
            _normalize_label('Parti & Organizasyon'): 'Parti & Organizasyon',
            _normalize_label('Hediyelik Eşya Ürünleri'): 'Hediyelik Eşya',
            _normalize_label('Promosyon Ürünleri'): 'Promosyon Ürünleri',
            _normalize_label('Spor ve Sağlık Ürünleri'): 'Spor & Sağlık',
            _normalize_label('Takı ve Aksesuar Ürünleri'): 'Takı & Moda Aksesuar',
            _normalize_label('Telefon - Tablet Aksesuar'): 'Telefon & Tablet Aksesuarları',
            _normalize_label('Özel Ürünler'): 'Özel Ürünler',
            _normalize_label('Tv Shop Ürünleri'): 'TV SHOP',
        }

        normalized_root = _normalize_label(parts[0])
        public_root = root_map.get(normalized_root)
        if not public_root:
            public_root = parts[0].strip()

        if public_root == 'TV SHOP':
            if len(parts) < 2:
                return [public_root]
            tv_sub = _normalize_label(parts[1])
            tv_shop_map = {
                _normalize_label('Elektronik Malzeme'): ('Elektronik & Hobi', 'Elektronik Malzeme'),
                _normalize_label('Hobi'): ('Elektronik & Hobi', 'Hobi'),
                _normalize_label('Kişisel Bakım Ürünleri'): ('Kozmetik & Kişisel Bakım', 'Kişisel Bakım Ürünleri'),
                _normalize_label('Masaj Aletleri'): ('Kozmetik & Kişisel Bakım', 'Masaj Aletleri'),
                _normalize_label('Pratik Ev Aletleri'): ('Ev & Yaşam', 'Pratik Ev Aletleri'),
                _normalize_label('Pratik Mutfak Aletleri'): ('Ev & Yaşam', 'Mutfak'),
                _normalize_label('Sağlık Bakım Kozmetik'): ('Spor & Sağlık', 'Sağlık Bakım Kozmetik'),
                _normalize_label('Spor Ürünleri'): ('Spor & Sağlık', 'Spor Ürünleri'),
                _normalize_label('Temizlik Aletleri'): ('Ev & Yaşam', 'Temizlik Aletleri'),
                _normalize_label('Tv Shop Oto'): ('Oto Aksesuarları',),
            }
            mapped_path = tv_shop_map.get(tv_sub, ())
            if not mapped_path:
                return []
            return list(mapped_path)

        cleaned = [p for p in [public_root] + parts[1:] if p]
        return cleaned[:3]

    def _find_or_create_public_category_path(self, parts):
        """E-ticaret kategori yolunu var ise al, yoksa oluştur."""
        self.ensure_one()
        if not parts:
            return self.env['product.public.category'].browse()

        PublicCategory = self.env['product.public.category']
        parent = False
        current_path = []

        for name in parts:
            name = (name or '').strip()
            if not name:
                continue
            current_path.append(name)
            domain = [('name', '=', name)]
            if parent:
                domain.append(('parent_id', '=', parent.id))
            else:
                domain.append(('parent_id', '=', False))

            category = PublicCategory.search(domain, limit=1)
            if not category:
                category = PublicCategory.create({
                    'name': name,
                    'parent_id': parent.id if parent else False,
                })
                _logger.info(
                    'Yeni e-ticaret kategorisi oluşturuldu: %s',
                    ' > '.join(current_path),
                )
            parent = category

        return parent

    def action_detect_variant_values(self):
        """XML'den varyant değerlerini tespit et ve varyant eşleştirme tablosunu hazırla

        XML feed'ini parse eder, field mapping'de 'variant_attribute' olarak
        işaretlenmiş alanlardaki tüm varyant değerlerini toplar ve
        varyant_mapping_ids tablosuna yeni kayıtlar olarak ekler.
        """
        self.ensure_one()

        try:
            xml_content = self._fetch_xml()
            elements = self._parse_xml(xml_content)
            flat_products = self._expand_nested_variants(elements)

            # Tüm varyant değerlerini topla
            detected_values = {}  # {key: {attribute, xml_attribute_name}}
            varattr_mappings = self.field_mapping_ids.filtered(
                lambda m: m.odoo_field == 'variant_attribute'
            )

            for element, v_elem, main_code in flat_products:
                data = self._extract_product_data(element)
                if v_elem is not None:
                    self._apply_variant_overrides(data, v_elem, main_code)
                    _logger.info("DEBUG import loop: product=%s, v_elem=True, _variant_attrs keys after override=%s",
                                 data.get('name','?'), list(data.get('_variant_attrs',{}).keys()))
                else:
                    _logger.info("DEBUG import loop: product=%s, v_elem=None (no variant)", data.get('name','?'))

                variant_attrs = data.get('_variant_attrs', {})
                for attr_id_str, attr_info in variant_attrs.items():
                    attr_names = attr_info.get('xml_attribute_names', [])
                    for idx, val in enumerate(attr_info['values']):
                        val = str(val).strip() if val else ''
                        if not val:
                            continue
                        attr_name = attr_names[idx] if idx < len(attr_names) else None
                        key = (attr_name, val) if attr_name else val
                        if key not in detected_values:
                            detected_values[key] = {
                                'attribute': attr_info.get('attribute'),
                                'xml_attribute_name': attr_name,
                            }

                # variant_group fallback
                vg = data.get('variant_group')
                if vg and str(vg).strip() not in detected_values:
                    detected_values[str(vg).strip()] = {'attribute': None, 'xml_attribute_name': None}

            if not detected_values:
                raise UserError(_(
                    'XML\'de varyant değeri bulunamadı.\n'
                    'Önce "Alan Eşleştirmeleri" sekmesinde bir alanı "Varyant Özellik Değeri" '
                    'olarak işaretleyip XML yolunu girin, ardından bu işlemi tekrar deneyin.'
                ))

            # Mevcut mapping değerlerini al (tekrar eklememek için)
            existing_pairs = set(
                (m.xml_attribute_name or '', m.xml_variant_value) for m in self.variant_mapping_ids
            )

            created_count = 0
            for key, info in sorted(detected_values.items(), key=lambda x: str(x[0])):
                if isinstance(key, tuple):
                    attr_name, val = key
                else:
                    attr_name, val = None, key

                if (attr_name or '', val) in existing_pairs:
                    continue

                attr = info.get('attribute')
                if not attr:
                    attr = self.env['product.attribute'].search(
                        [('name', '=', self.variant_attribute_name or 'Renk')], limit=1
                    )
                    if not attr:
                        _logger.info("Varyant tespit: attribute bulunamadı, atlanıyor: %s", val)
                        continue

                vals = {
                    'source_id': self.id,
                    'xml_variant_value': str(val)[:255],
                    'match_type': 'exact',
                    'active': True,
                    'attribute_id': attr.id,
                }
                if attr_name:
                    vals['xml_attribute_name'] = str(attr_name)[:255]

                self.env['xml.variant.mapping'].create(vals)
                created_count += 1

            raise UserError(_(
                'Varyant tespit tamamlandı!\n\n'
                '• %d yeni varyant değeri bulundu\n'
                '• %d adet eşleştirme kaydı oluşturuldu\n\n'
                'Her kaydın "Özellik (Attribute)" ve "Özellik Değeri" alanlarını '
                'Varyant Eşleştirmeleri sekmesinden el ile doldurun.'
            ) % (len(detected_values), created_count))

        except UserError:
            raise
        except Exception as e:
            raise UserError(_('Varyant tespit hatası: %s') % str(e))

    def action_sync_ecommerce_categories(self):
        """XML kategori maplerinden e-ticaret kategorilerini oluştur ve eşleştir."""
        self.ensure_one()
        force_sync = bool(self.env.context.get('force_ecommerce_sync', True))

        mappings = self.env['xml.category.mapping'].search([
            ('source_id', '=', self.id),
        ], order='xml_category')

        if not mappings:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Eşleme Kaydı Yok'),
                    'message': _('Önce "Şablon Yükle" ile kategori eşleştirmeleri oluşturun.'),
                    'type': 'warning',
                    'sticky': True,
                }
            }

        created_count = 0
        assigned_count = 0
        for mapping in mappings:
            public_path = self._public_category_path_from_xml(mapping.xml_category)
            if not public_path:
                continue
            public_category = self._find_or_create_public_category_path(public_path)
            if public_category and (force_sync or not mapping.ecommerce_category_ids):
                mapping.ecommerce_category_ids = [(6, 0, public_category.ids)]
                assigned_count += 1

            if public_category:
                created_count += 1

        message = _('%s kategori kaydı işlendi, %s ürün eşleşmesine e-ticaret kategorisi atandı.') % (
            len(mappings), assigned_count,
        )
        if created_count == 0 and assigned_count == 0:
            message = _('E-ticaret kategorisi için yeni bir eşleme bulunamadı.')

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('E-Ticaret Kategorileri'),
                'message': message,
                'type': 'success',
                'sticky': False,
            }
        }

    def _category_alias_map(self):
        """XML kategori isimlerini mevcut kategori ağacına yaklaştır."""
        return {
            'akilli teknolojiler': 'Akıllı Teknolojiler',
            'aparat ceviriciler': 'Dönüştürücüler',
            'donusturucu aparatlar': 'Dönüştürücüler',
            'mini aparat ceviriciler': 'Dönüştürücüler',
            'arac aksesuarlari': 'Araç Aksesuarları',
            'arac sarjlari': 'Araç Şarjları',
            'hizli arac sarjlari': 'Araç Şarjları',
            'super hizli arac sarjlari': 'Süper Hızlı Şarjlar',
            'bluetooth kulakliklar': 'Kulaklıklar',
            'bt kulakliklar kulak ustu': 'Bluetooth Kulak Üstü',
            'bt kulakliklar kulak ici': 'Bluetooth Kulak İçi',
            'bluetooth speakerlar': 'Hoparlörler',
            'speakerlar': 'Hoparlörler',
            'kablosuz hoparloler': 'Taşınabilir Hoparlörler',
            'ses bombalari': 'Taşınabilir Hoparlörler',
            'ses sistemleri': 'Ses Sistemleri',
            'depolama aygitlari': 'Depolama',
            'micro': 'Hafıza Kartları',
            'micro elt': 'Hafıza Kartları',
            'micro prm': 'Hafıza Kartları',
            'otg iphone': 'Dönüştürücüler',
            'otg type c': 'Dönüştürücüler',
            'usb': 'USB Flash Bellek',
            'usb mini': 'USB Flash Bellek',
            'usb prm': 'USB Flash Bellek',
            'ev sarjlari': 'Şarj Cihazları',
            'duvar sarjlari': 'Duvar Şarjları',
            'hizli sarjlar': 'Süper Hızlı Şarjlar',
            'super hizli sarjlar': 'Süper Hızlı Şarjlar',
            'kablolar': 'Kablolar',
            'guc ve veri aktarim kablolari': 'Güç ve Veri Kabloları',
            'guc ve veri aktarim kablolari 2 m': 'Güç ve Veri Kabloları',
            'ses aktarim kablolari': 'Ses Kabloları',
            'yuksek hizli kablolar': 'Hızlı Şarj Kabloları',
            'kablolu kulakliklar': 'Kablolu Kulaklıklar',
            'kablolu kulakliklar 3 5 mm': 'Kablolu Kulaklıklar',
            'powerbanklar': 'Powerbanklar',
            'super hizli powerbanklar': 'Süper Hızlı Powerbanklar',
            'tablet aksesuarlari': 'Tablet Aksesuarları',
            'tabletler': 'Tabletler',
            'telefon aksesuarlari': 'Telefon Aksesuarları',
            'masa ustu standlar': 'Telefon Aksesuarları',
            'mobil cihaz aksesuarlari': 'Mobil Cihaz Aksesuarları',
        }

    def _find_matching_category_records(self, xml_category):
        """XML kategori adına göre en uygun iç ve website kategorilerini bul."""
        alias_map = self._category_alias_map()
        parts = self._split_xml_category_path(xml_category)
        normalized_parts = [self._normalize_category_name(part) for part in parts]

        candidates = []
        if xml_category:
            candidates.append(xml_category.strip())
        for normalized in reversed(normalized_parts):
            if normalized in alias_map:
                candidates.append(alias_map[normalized])
        for part in reversed(parts):
            candidates.append(part)

        seen = set()
        ordered_candidates = []
        for candidate in candidates:
            norm = self._normalize_category_name(candidate)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            ordered_candidates.append(candidate)

        ProductCategory = self.env['product.category']
        PublicCategory = self.env['product.public.category']

        product_category = False
        ecommerce_categories = PublicCategory.browse()

        for candidate in ordered_candidates:
            if not product_category:
                product_category = ProductCategory.search([('name', '=ilike', candidate)], limit=1)
            if not ecommerce_categories:
                ecommerce_categories = PublicCategory.search([('name', '=ilike', candidate)], limit=1)
            if product_category and ecommerce_categories:
                break

        return product_category, ecommerce_categories

    def _sync_template_category_mappings(self, mapping_data):
        """Şablon yüklendikten sonra XML içindeki kategorileri kategori eşleme sekmesine taşı."""
        self.ensure_one()

        category_path = mapping_data.get('category')
        if not category_path or not self.xml_url:
            return 0, 0

        subcategory_path = mapping_data.get('extra1')
        xml_content = self._fetch_xml()
        products = self._parse_xml(xml_content)
        if not products:
            return 0

        separator = self.category_separator or ' > '
        category_values = set()
        for element in products:
            category_name = self._get_element_value(element, category_path)
            subcategory_name = self._get_element_value(element, subcategory_path) if subcategory_path else None

            if not category_name:
                continue

            category_name = str(category_name).strip()
            subcategory_name = str(subcategory_name).strip() if subcategory_name else ''
            if not category_name:
                continue

            full_path = category_name
            if subcategory_name:
                full_path = f"{category_name}{separator}{subcategory_name}"
            category_values.add(full_path)

        if not category_values:
            return 0, 0

        Mapping = self.env['xml.category.mapping']
        existing_rows = Mapping.search_read(
            [('source_id', '=', self.id), ('xml_category', 'in', list(category_values))],
            ['xml_category', 'odoo_category_id', 'ecommerce_category_ids'],
        )
        existing_by_category = {
            row['xml_category']: row for row in existing_rows if row.get('xml_category')
        }

        to_create = sorted(category_values - set(existing_by_category))
        start_sequence = 10 * (len(existing_rows) + 1)
        auto_matched_count = 0

        for index, xml_category in enumerate(to_create):
            product_category, ecommerce_categories = self._find_matching_category_records(xml_category)
            ecommerce_path = self._public_category_path_from_xml(xml_category)
            if ecommerce_path:
                ecommerce_category = self._find_or_create_public_category_path(ecommerce_path)
                if ecommerce_category:
                    ecommerce_categories = ecommerce_category
            Mapping.create({
                'source_id': self.id,
                'sequence': start_sequence + (index * 10),
                'xml_category': xml_category,
                'match_type': 'exact',
                'odoo_category_id': product_category.id if product_category else False,
                'ecommerce_category_ids': [(6, 0, ecommerce_categories.ids)] if ecommerce_categories else False,
                'active': True,
            })
            if product_category or ecommerce_categories:
                auto_matched_count += 1

        existing_mappings = Mapping.search([
            ('source_id', '=', self.id),
            ('xml_category', 'in', list(category_values)),
        ])
        for mapping in existing_mappings:
            vals = {}
            if not mapping.odoo_category_id or not mapping.ecommerce_category_ids:
                product_category, ecommerce_categories = self._find_matching_category_records(mapping.xml_category)
                if not ecommerce_categories:
                    ecommerce_path = self._public_category_path_from_xml(mapping.xml_category)
                    if ecommerce_path:
                        ecommerce_category = self._find_or_create_public_category_path(ecommerce_path)
                        if ecommerce_category:
                            ecommerce_categories = ecommerce_category
                if not mapping.odoo_category_id and product_category:
                    vals['odoo_category_id'] = product_category.id
                if not mapping.ecommerce_category_ids and ecommerce_categories:
                    vals['ecommerce_category_ids'] = [(6, 0, ecommerce_categories.ids)]
            if vals:
                mapping.write(vals)
                auto_matched_count += 1

        return len(to_create), auto_matched_count

    # ══════════════════════════════════════════════════════════════════════════
    # XML PARSING
    # ══════════════════════════════════════════════════════════════════════════

    def _fetch_xml(self):
        """XML'i URL'den çek"""
        self.ensure_one()

        try:
            if self.xml_template == 'woocommerce_api':
                return self._fetch_woocommerce_api_xml()
            if self.xml_template in ('tesan', 'tesan_soap'):
                return self._fetch_tesan_soap_xml()

            headers = {
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/133.0.0.0 Safari/537.36'
                ),
                'Accept': 'application/xml, text/xml, application/xhtml+xml, text/html;q=0.9, */*;q=0.8',
                'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
            }

            auth = None
            if self.xml_username and self.xml_password:
                auth = (self.xml_username, self.xml_password)

            # Bazı XML servisleri yavaş yanıt verebiliyor; timeout + retry ile daha stabil çalıştır.
            # timeout=(connect, read)
            last_exc = None
            response = None
            session = requests.Session()
            last_text = None
            for attempt in range(1, 4):
                try:
                    # Bazı OpenCart tabanlı feedlerde session/referer beklenebiliyor.
                    if 'tahtakale' in (self.xml_url or '').lower():
                        try:
                            home_url = 'https://www.tahtakaletoptanticaret.com/'
                            session.get(home_url, headers=headers, timeout=(15, 60))
                        except Exception:
                            pass

                    response = session.get(
                        self.xml_url,
                        headers=headers,
                        auth=auth,
                        allow_redirects=True,
                        timeout=(15, 600),
                    )
                    response.raise_for_status()
                    last_text = response.text or ''
                    if 'Maximum sınıra ulaştınız' in last_text and attempt < 3:
                        time.sleep(5 * attempt)
                        continue
                    break
                except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
                    last_exc = e
                    if attempt >= 3:
                        raise
                    time.sleep(2 if attempt == 1 else 5)
            if response is None and last_exc:
                raise last_exc

            # Encoding düzeltme - content bytes olarak al
            # XML header'dan encoding'i oku
            content = response.content

            # XML declaration'dan encoding tespit et
            encoding = 'utf-8'
            if content.startswith(b'<?xml'):
                match = re.search(rb'encoding=["\']([^"\']+)["\']', content[:200])
                if match:
                    encoding = match.group(1).decode('ascii').lower()
                    _logger.debug(f"XML encoding tespit edildi: {encoding}")

            # Türkçe karakter sorunları için encoding denemeleri
            try:
                # Önce belirtilen encoding'i dene
                xml_text = content.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                # Hata varsa sırayla encoding'leri dene
                for enc in ['utf-8', 'iso-8859-9', 'windows-1254', 'latin1']:
                    try:
                        xml_text = content.decode(enc)
                        _logger.info(f"XML {enc} encoding ile decode edildi")
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    # Hiçbiri çalışmazsa hataları ignore et
                    xml_text = content.decode('utf-8', errors='ignore')
                    _logger.warning("XML decode hatası - bazı karakterler kaybolabilir")

            stripped = (xml_text or '').lstrip()
            content_type = (response.headers.get('Content-Type') or '').lower()
            if not stripped.startswith('<') or content_type.startswith('text/html'):
                preview = stripped[:200].replace('\n', ' ').strip()
                raise UserError(
                    _('XML yerine HTML/metin yaniti dondu. Icerik: %s') % (preview or _('Bos yanit'))
                )

            return xml_text

        except requests.exceptions.RequestException as e:
            raise UserError(_('XML çekilemedi: %s') % str(e))

    def _build_woocommerce_api_url(self, page=1, per_page=100):
        """WooCommerce Store API URL'ine sayfalama parametreleri ekle."""
        parsed = urlparse((self.xml_url or '').strip())
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query['page'] = str(page)
        query['per_page'] = str(per_page)
        new_query = urlencode(query)
        return urlunparse(parsed._replace(query=new_query))

    def _fetch_woocommerce_api_xml(self):
        """WooCommerce Store API'den ürünleri çekip normalize XML'e dönüştür."""
        headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/133.0.0.0 Safari/537.36'
            ),
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
        }
        auth = None
        if self.xml_username and self.xml_password:
            auth = (self.xml_username, self.xml_password)

        session = requests.Session()
        products = []
        page = 1
        per_page = 100

        while True:
            url = self._build_woocommerce_api_url(page=page, per_page=per_page)
            response = session.get(
                url,
                headers=headers,
                auth=auth,
                allow_redirects=True,
                timeout=(15, 180),
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise UserError(_('WooCommerce API listesi bekleniyordu, farkli veri dondu.'))

            if not payload:
                break

            products.extend(payload)
            total_pages = response.headers.get('X-WP-TotalPages')
            if total_pages and page >= int(total_pages):
                break
            if len(payload) < per_page:
                break
            page += 1

        xml_text = self._woocommerce_api_payload_to_xml(products, session, headers, auth)
        _logger.info("WooCommerce API: %d ürün/variasyon normalize edildi", len(products))
        return xml_text

    def _woocommerce_api_payload_to_xml(self, products, session, headers, auth):
        """WooCommerce Store API ürün listesini standart XML parse akışına uydur."""

        def _minor_to_price(price_info):
            if not price_info:
                return ''
            minor_unit = int(price_info.get('currency_minor_unit') or 0)
            raw = str(price_info.get('price') or price_info.get('regular_price') or '0').strip()
            if not raw:
                return ''
            try:
                raw_int = int(raw)
                return str(raw_int / (10 ** minor_unit))
            except Exception:
                return raw

        def _minor_to_regular(price_info):
            if not price_info:
                return ''
            minor_unit = int(price_info.get('currency_minor_unit') or 0)
            raw = str(price_info.get('regular_price') or price_info.get('price') or '0').strip()
            if not raw:
                return ''
            try:
                raw_int = int(raw)
                return str(raw_int / (10 ** minor_unit))
            except Exception:
                return raw

        def _choose_category(product_data):
            categories = product_data.get('categories') or []
            if not categories:
                return ''
            names = [c.get('name') for c in categories if c.get('name')]
            return names[-1] if names else ''

        def _brand_name(product_data):
            brands = product_data.get('brands') or []
            return (brands[0].get('name') if brands and brands[0].get('name') else '')

        def _attributes_text(product_data):
            attrs = []
            for attr in product_data.get('attributes') or []:
                terms = [term.get('name') for term in (attr.get('terms') or []) if term.get('name')]
                if terms:
                    attrs.append('%s: %s' % (attr.get('name') or '', ', '.join(terms)))
            return ' | '.join([item for item in attrs if item])

        def _image_urls(product_data):
            urls = []
            for image in product_data.get('images') or []:
                src = (image.get('src') or '').strip()
                if src and src not in urls:
                    urls.append(src)
            return urls

        def _variation_label(parent_product, variation_data):
            attrs = variation_data.get('variation') or variation_data.get('attributes') or []
            if isinstance(attrs, str):
                return attrs.replace(':', ': ').strip()
            attr_terms = {attr.get('taxonomy'): {term.get('slug'): term.get('name') for term in (attr.get('terms') or [])}
                          for attr in (parent_product.get('attributes') or []) if attr.get('taxonomy')}
            labels = []
            for attr in attrs:
                if not isinstance(attr, dict):
                    continue
                name = (attr.get('name') or '').strip()
                value = (attr.get('value') or '').strip()
                mapped = attr_terms.get(name, {}).get(value)
                if mapped:
                    value = mapped
                value = value.replace('-', ' ').strip()
                if value:
                    labels.append(value.upper() if value.islower() else value)
            return ' / '.join(labels)

        def _fetch_variation(variation_id):
            base_url = (self.xml_url or '').split('?')[0].rstrip('/')
            response = session.get(
                '%s/%s' % (base_url, variation_id),
                headers=headers,
                auth=auth,
                allow_redirects=True,
                timeout=(15, 120),
            )
            response.raise_for_status()
            return response.json()

        root = ET.Element('products')

        for product in products:
            ptype = (product.get('type') or '').strip().lower()
            if ptype == 'variation':
                continue

            rows = []
            if ptype == 'variable' and product.get('variations'):
                for variation_ref in product.get('variations') or []:
                    variation_id = variation_ref.get('id')
                    if not variation_id:
                        continue
                    try:
                        variation = _fetch_variation(variation_id)
                    except Exception as exc:
                        _logger.warning("WooCommerce variation okunamadi (%s): %s", variation_id, exc)
                        continue
                    label = _variation_label(product, variation)
                    rows.append({
                        'external_id': str(product.get('id') or ''),
                        'stock_id': str(variation.get('id') or ''),
                        'variant_group': str(product.get('id') or product.get('sku') or ''),
                        'name': '%s (%s)' % (product.get('name') or '', label) if label else (product.get('name') or ''),
                        'sku': (variation.get('sku') or product.get('sku') or '').strip(),
                        'barcode': '',
                        'description': variation.get('description') or product.get('description') or '',
                        'short_description': variation.get('short_description') or product.get('short_description') or '',
                        'price': _minor_to_price(variation.get('prices') or {}),
                        'regular_price': _minor_to_regular(variation.get('prices') or product.get('prices') or {}),
                        'stock': '1' if variation.get('is_in_stock') else '0',
                        'currency': (variation.get('prices') or product.get('prices') or {}).get('currency_code') or '',
                        'category': _choose_category(product),
                        'brand': _brand_name(product),
                        'attributes': _attributes_text(product),
                        'images': _image_urls(variation) or _image_urls(product),
                    })
            else:
                rows.append({
                    'external_id': str(product.get('id') or ''),
                    'stock_id': str(product.get('id') or ''),
                    'variant_group': str(product.get('id') or product.get('sku') or ''),
                    'name': product.get('name') or '',
                    'sku': (product.get('sku') or '').strip(),
                    'barcode': '',
                    'description': product.get('description') or '',
                    'short_description': product.get('short_description') or '',
                    'price': _minor_to_price(product.get('prices') or {}),
                    'regular_price': _minor_to_regular(product.get('prices') or {}),
                    'stock': '1' if product.get('is_in_stock') else '0',
                    'currency': (product.get('prices') or {}).get('currency_code') or '',
                    'category': _choose_category(product),
                    'brand': _brand_name(product),
                    'attributes': _attributes_text(product),
                    'images': _image_urls(product),
                })

            for row in rows:
                item = ET.SubElement(root, 'product')
                for key, value in (
                    ('SKU', row['sku']),
                    ('Barcode', row['barcode']),
                    ('Name', row['name']),
                    ('Price', row['price']),
                    ('RegularPrice', row['regular_price']),
                    ('Stock', row['stock']),
                    ('Category', row['category']),
                    ('Brand', row['brand']),
                    ('Currency', row['currency']),
                    ('Attributes', row['attributes']),
                    ('ExternalProductId', row['external_id']),
                    ('SourceStockId', row['stock_id']),
                    ('VariantGroup', row['variant_group']),
                    ('UsageClass', 'commercial'),
                ):
                    child = ET.SubElement(item, key)
                    child.text = value or ''

                desc = ET.SubElement(item, 'Description')
                desc.text = row['description'] or ''
                short_desc = ET.SubElement(item, 'ShortDescription')
                short_desc.text = row['short_description'] or ''

                if row['images']:
                    img = ET.SubElement(item, 'Image')
                    img.text = row['images'][0]
                    images_el = ET.SubElement(item, 'Images')
                    for image_url in row['images']:
                        img_el = ET.SubElement(images_el, 'Image')
                        img_el.text = image_url

        return ET.tostring(root, encoding='unicode')

    def _fetch_tesan_soap_xml(self):
        """Tesan SOAP servislerinden ürün verilerini çekip normalize XML'e dönüştür."""

        def _soap_url():
            return (self.xml_url or 'http://www.tesaniletisim.com/webservice/ProductServices.asmx').strip()

        def _soap_envelope(method, body_xml=''):
            header = (
                '<soap:Header>'
                '<AuthUsers xmlns="http://tempuri.org/">'
                '<userName>%s</userName>'
                '<password>%s</password>'
                '<token>%s</token>'
                '</AuthUsers>'
                '</soap:Header>'
            ) % (
                self.xml_username or '',
                self.xml_password or '',
                self.xml_token or '',
            )
            body = '<soap:Body><%s xmlns="http://tempuri.org/">%s</%s></soap:Body>' % (
                method, body_xml or '', method,
            )
            return (
                '<?xml version="1.0" encoding="utf-8"?>'
                '<soap:Envelope '
                'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
                'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
                'xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
                '%s%s</soap:Envelope>'
            ) % (header, body)

        def _soap_call(method, body_xml=''):
            headers = {
                'Content-Type': 'text/xml; charset=utf-8',
                'SOAPAction': 'http://tempuri.org/%s' % method,
                'User-Agent': 'mobilsoft_xml_import/tesan_soap',
            }
            auth = None
            if self.xml_username and self.xml_password:
                auth = (self.xml_username, self.xml_password)
            response = requests.post(
                _soap_url(),
                data=_soap_envelope(method, body_xml).encode('utf-8'),
                headers=headers,
                auth=auth,
                timeout=(15, 300),
            )
            response.raise_for_status()
            return ET.fromstring(response.text)

        def _strip_ns(elem):
            for el in elem.iter():
                if '}' in el.tag:
                    el.tag = el.tag.split('}', 1)[1]

        def _get_text(parent, tag, default=''):
            el = parent.find(tag)
            if el is None or el.text is None:
                return default
            return el.text.strip()

        def _parse_categories(root):
            _strip_ns(root)
            items = []
            for cat in root.findall('.//GetProductCategoriesResult/ProductCategory'):
                items.append({
                    'LowerGroupId': _get_text(cat, 'LowerGroupId'),
                    'MainGroup': _get_text(cat, 'MainGroup'),
                    'LowerGroup': _get_text(cat, 'LowerGroup'),
                    'Departman': _get_text(cat, 'Departman'),
                    'ProductCatId': _get_text(cat, 'ProductCatId'),
                    'ProductCat': _get_text(cat, 'ProductCat'),
                    'ProductTypeId': _get_text(cat, 'ProductTypeId'),
                    'ProductType': _get_text(cat, 'ProductType'),
                    'BrandId': _get_text(cat, 'BrandId'),
                    'Brand': _get_text(cat, 'Brand'),
                })
            return items

        def _parse_product_list(root):
            _strip_ns(root)
            items = []
            for product in root.findall('.//GetProductListsResult/ProductList'):
                items.append({
                    'StockId': _get_text(product, 'StockId'),
                    'StockCode': _get_text(product, 'StockCode'),
                    'ProductCode': _get_text(product, 'ProductCode'),
                    'Product': _get_text(product, 'Product'),
                    'Unit': _get_text(product, 'Unit'),
                    'Tax': _get_text(product, 'Tax'),
                    'LowerGroupId': _get_text(product, 'LowerGroupId'),
                    'SpecialCode': _get_text(product, 'SpecialCode'),
                    'ProductCatId': _get_text(product, 'ProductCatId'),
                    'ProductTypeId': _get_text(product, 'ProductTypeId'),
                    'BrandId': _get_text(product, 'BrandId'),
                    'ProductId': _get_text(product, 'ProductId'),
                    'ProductStatus': _get_text(product, 'ProductStatus'),
                    'StockStatus': _get_text(product, 'StockStatus'),
                    'Barcode': _get_text(product, 'Barcode'),
                })
            return items

        def _parse_features(root):
            _strip_ns(root)
            out = {}
            for feat in root.findall('.//GetProductFeaturesResult/ProductFeatures'):
                product_id = _get_text(feat, 'ProductId')
                features = _get_text(feat, 'Features')
                if product_id and features:
                    out[product_id] = html.unescape(features)
            return out

        def _parse_images(root):
            _strip_ns(root)
            out = {}
            for image in root.findall('.//GetProductImagesResult/ProductImages'):
                stock_id = _get_text(image, 'StockId')
                url = _get_text(image, 'Image')
                if stock_id and url:
                    out.setdefault(stock_id, []).append(url)
            return out

        def _parse_prices(root):
            _strip_ns(root)
            out = {}
            for price in root.findall('.//GetStockPricesResult/StockPrice'):
                stock_id = _get_text(price, 'StockId')
                product_id = _get_text(price, 'ProductId')
                if stock_id and product_id:
                    out[(stock_id, product_id)] = {
                        'Price': _get_text(price, 'Price'),
                        'Currency': _get_text(price, 'Currency'),
                        'StandartPrice': _get_text(price, 'StandartPrice'),
                        'StandartPriceCurrency': _get_text(price, 'StandartPriceCurrency'),
                    }
            return out

        def _parse_stocks(root):
            _strip_ns(root)
            out = {}
            for stock in root.findall('.//GetWareHouseStocksResult/WareHouseStock'):
                stock_id = _get_text(stock, 'StockId')
                product_id = _get_text(stock, 'ProductId')
                qty = _get_text(stock, 'Quantity')
                if not stock_id or not product_id:
                    continue
                try:
                    quantity = int(float(qty))
                except Exception:
                    quantity = 0
                key = (stock_id, product_id)
                out[key] = out.get(key, 0) + quantity
            return out

        def _best_category(categories, product):
            if not categories:
                return {}
            full_key = (
                product.get('LowerGroupId'),
                product.get('ProductCatId'),
                product.get('ProductTypeId'),
                product.get('BrandId'),
            )
            for category in categories:
                if (
                    category.get('LowerGroupId'),
                    category.get('ProductCatId'),
                    category.get('ProductTypeId'),
                    category.get('BrandId'),
                ) == full_key:
                    return category
            for category in categories:
                if category.get('ProductCatId') and category.get('ProductCatId') == product.get('ProductCatId'):
                    return category
            for category in categories:
                if category.get('LowerGroupId') and category.get('LowerGroupId') == product.get('LowerGroupId'):
                    return category
            return categories[0]

        def _classify_usage(name, main_group, lower_group, description):
            haystack = ' '.join([name or '', main_group or '', lower_group or '', description or '']).lower()
            service_tokens = (
                ' hizmet', 'gider', 'masraf', 'nakliye', 'kargo', 'akaryakit',
                'telekom', 'seyahat', 'abonelik', 'komisyon', 'premium', 'kep',
            )
            operational_tokens = ('ambalaj', 'karton', 'bant', 'etiket', 'paketleme', 'koli')
            internal_tokens = ('demirbas', 'demirbaş', 'ofis', 'raf', 'ates olcer', 'ateş ölçer')
            if any(token in haystack for token in service_tokens):
                return 'service'
            if any(token in haystack for token in operational_tokens):
                return 'operational'
            if any(token in haystack for token in internal_tokens):
                return 'internal'
            return 'commercial'

        def _variant_group(sku, name, product_id, stock_id):
            base_sku = (sku or '').strip().split()[0]
            base_name = (name or '').strip()
            if '(' in base_name and ')' in base_name:
                base_name = base_name.split('(', 1)[0].strip()
            return base_sku or base_name or product_id or stock_id or ''

        if not (self.xml_username and self.xml_password and self.xml_token):
            raise UserError(_('Tesan SOAP için kullanıcı adı, şifre ve token zorunludur.'))

        categories = _parse_categories(_soap_call('GetProductCategories'))
        products = _parse_product_list(_soap_call('GetProductLists', '<_departman>0</_departman>'))
        features = _parse_features(_soap_call('GetProductFeatures'))
        images = _parse_images(_soap_call('GetProductImages'))
        prices = _parse_prices(_soap_call('GetStockPrices'))
        stocks = _parse_stocks(_soap_call('GetWareHouseStocks'))

        root = ET.Element('Products', attrib={'generated_at': datetime.utcnow().isoformat() + 'Z'})

        for product in products:
            if product.get('ProductStatus', '').lower() not in ('true', '1', 'yes'):
                continue

            stock_id = product.get('StockId', '')
            product_id = product.get('ProductId', '')
            price_key = (stock_id, product_id)
            category = _best_category(categories, product)
            main_group = category.get('MainGroup') or category.get('Departman') or ''
            lower_group = category.get('LowerGroup') or category.get('ProductCat') or ''
            brand = category.get('Brand') or ''
            sku = product.get('ProductCode') or product.get('StockCode') or ''
            barcode = product.get('Barcode') or ''
            name = product.get('Product') or ''
            description = features.get(product_id, '')
            price_info = prices.get(price_key, {})
            usage_class = _classify_usage(name, main_group, lower_group, description)
            variant_group = _variant_group(sku, name, product_id, stock_id)
            image_urls = images.get(stock_id, [])
            stock_qty = stocks.get(price_key, 0)

            item = ET.SubElement(root, 'Product')
            for tag, value in (
                ('SKU', sku),
                ('Barcode', barcode),
                ('Name', name),
                ('Description', description),
                ('Category', main_group),
                ('SubCategory', lower_group),
                ('Brand', brand),
                ('Price', price_info.get('Price', '')),
                ('CostPrice', price_info.get('StandartPrice', '') or price_info.get('Price', '')),
                ('Currency', price_info.get('Currency', '') or price_info.get('StandartPriceCurrency', '')),
                ('Stock', str(stock_qty)),
                ('Tax', product.get('Tax') or ''),
                ('ProductId', product_id),
                ('StockId', stock_id),
                ('ExternalProductId', product_id),
                ('SourceStockId', stock_id),
                ('VariantGroup', variant_group),
                ('UsageClass', usage_class),
                ('SpecialCode', product.get('SpecialCode') or ''),
                ('Unit', product.get('Unit') or ''),
            ):
                child = ET.SubElement(item, tag)
                child.text = value or ''

            if image_urls:
                image = ET.SubElement(item, 'Image')
                image.text = image_urls[0]
                images_el = ET.SubElement(item, 'Images')
                for image_url in image_urls:
                    image_el = ET.SubElement(images_el, 'Image')
                    image_el.text = image_url

        _logger.info("Tesan SOAP: %d ürün normalize edildi", len(root.findall('./Product')))
        return ET.tostring(root, encoding='unicode')

    def _parse_xml(self, xml_content):
        """XML içeriğini parse et"""
        self.ensure_one()

        try:
            # String parse et - eğer byte ise decode et
            if isinstance(xml_content, bytes):
                # Encoding denemeleri
                for enc in ['utf-8', 'iso-8859-9', 'windows-1254', 'latin1']:
                    try:
                        xml_content = xml_content.decode(enc)
                        _logger.info(f"XML {enc} ile decode edildi")
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    xml_content = xml_content.decode('utf-8', errors='ignore')
                    _logger.warning("XML decode hatası - bazı karakterler kaybolmuş olabilir")

            # WordPress / WooCommerce WXR exportlarını namespace'leri koruyarak işle.
            if 'wordpress.org/export/' in (xml_content or '') and '<rss' in (xml_content or ''):
                root = ET.fromstring(xml_content)
                products = self._parse_wordpress_wxr_xml(root)
                _logger.info(
                    "WordPress WXR Parse: %d ürün bulundu (attachment ve sayfalar filtrelendi)",
                    len(products),
                )
                return products

            # XML namespace'leri temizle
            xml_content = re.sub(r'\sxmlns[^"]*"[^"]*"', '', xml_content)
            xml_content = re.sub(r'\sxmlns=[^"]*"[^"]*"', '', xml_content)

            root = ET.fromstring(xml_content)

            # ═══════════════════════════════════════════════════════════════
            # INDEX GRUP / NETEX: İç içe yapıyı düzleştir
            # INDEXGRUP > KATEGORI > GRUP > URUN → düz URUN listesi
            # Her URUN elementine _KATEGORI ve _GRUP bilgisini attribute olarak enjekte et
            # ═══════════════════════════════════════════════════════════════
            if self.xml_template in ('indexgrup', 'netex'):
                products = self._parse_indexgrup_xml(root)
                _logger.info(
                    "Index Grup/Netex XML Parse: %d ürün bulundu (iç içe yapıdan düzleştirildi)",
                    len(products),
                )
                return products

            # XPath ile ürünleri bul
            xpath = self.root_element
            if xpath.startswith('//'):
                xpath = '.' + xpath

            products = root.findall(xpath)

            _logger.info(f"XML Parse: {len(products)} ürün bulundu (xpath: {xpath})")

            if not products:
                # Alternatif yolları dene (İngilizce ve Türkçe)
                alt_paths = ['.//Product', './/product', './/item', './/entry',
                            './/urun', './/Urun', './/URUN']
                for alt_path in alt_paths:
                    products = root.findall(alt_path)
                    if products:
                        _logger.info(f"Alternatif xpath ile {len(products)} ürün bulundu: {alt_path}")
                        break

            return products

        except ET.ParseError as e:
            raise UserError(_('XML parse hatası: %s') % str(e))

    def _expand_nested_variants(self, elements):
        """<Variants>/<Variant> içeren ürünleri düzleştir: her varyant ayrı kayıt olsun.
        
        Varyantsız ürün → [(element, None, None)]
        Varyantlı ürün   → [(element, variant_element, main_code), ...]
        """
        flat = []
        for el in elements:
            variants_el = el.find('Variants')
            if variants_el is not None:
                variant_list = variants_el.findall('Variant')
                if variant_list:
                    main_code = (el.findtext('MainCode') or '').strip()
                    for v_el in variant_list:
                        flat.append((el, v_el, main_code))
                    continue
            flat.append((el, None, None))
        return flat

    def _strip_variant_prefix(self, xml_path):
        """XML yolundaki 'Variants/Variant/' ön ekini temizler.

        Örn: 'Variants/Variant/Color' → 'Color'
             'Variants/Variant/VariantAttributes/Attribute' → 'VariantAttributes/Attribute'
        """
        parts = xml_path.split('/')
        try:
            variant_idx = [p.lower() for p in parts].index('variant')
            return '/'.join(parts[variant_idx + 1:])
        except ValueError:
            return xml_path

    def _apply_variant_overrides(self, data, v_elem, main_code):
        """Varyant XML elementinden alınan verilerle data dict'ini güncelle."""
        barcode = (v_elem.findtext('Barcode') or '').strip()
        v_code = (v_elem.findtext('VariantCode') or '').strip()
        v_stock = (v_elem.findtext('Stock') or '').strip()
        v_price = (v_elem.findtext('Price') or '').strip()

        if barcode:
            data['barcode'] = barcode
        if v_code:
            data['sku'] = v_code
        if v_stock:
            data['stock'] = v_stock
        if v_price:
            data['price'] = v_price
            data['cost_price'] = v_price
        if main_code:
            data['variant_group'] = main_code

        images = []
        for img in v_elem.findall('./Images/Image'):
            if img.text:
                url = img.text.strip()
                if url and url.startswith('http'):
                    images.append(url)
        if images:
            data['image'] = images[0]
            if len(images) > 1:
                data['extra_images'] = images[1:]

        # Varyant attribute'larını v_elem'den çıkar (doğru varyanta ait değerler)
        # _extract_product_data her zaman product element'inden okur → ilk varyant
        for mapping in self.field_mapping_ids.filtered(
            lambda m: m.odoo_field == 'variant_attribute'
        ):
            rel_path = self._strip_variant_prefix(mapping.xml_path)
            _logger.info("DEBUG _apply_variant_overrides: mapping=%s, rel_path=%s, has_subpaths=%s",
                         mapping.xml_path, rel_path, bool(mapping.variant_name_subpath and mapping.variant_value_subpath))
            if mapping.variant_name_subpath and mapping.variant_value_subpath:
                # Otomatik düzeltme: XML Yolu "Name" veya "Value" ile bitiyorsa,
                # parent element'e (Attribute) çek. Kullanıcı yanlışlıkla son parçayı
                # seçmiş olabilir; Name/Value alt öğelerinin parent'ı kullanılmalı.
                path_parts = rel_path.split('/')
                if path_parts and path_parts[-1].lower() in ('name', 'value'):
                    corrected = '/'.join(path_parts[:-1])
                    _logger.warning(
                        "XML yolu '%s' '%s' ile bitiyor. Varyant attributeları için "
                        "parent path '%s' kullanıldı (subpath: Name/Value). "
                        "Lütfen field mapping'de XML Yolu'nu '%s' olarak düzeltin.",
                        mapping.xml_path, path_parts[-1], corrected, corrected
                    )
                    rel_path = corrected
                pairs = self._get_nested_variant_attributes(
                    v_elem, mapping, override_path=rel_path
                )
                _logger.info("DEBUG _apply_variant_overrides: pairs from _get_nested_variant_attributes=%s", pairs)
                if not pairs:
                    continue
                variant_attrs = data.setdefault('_variant_attrs', {})
                for attr_name, attr_value in pairs:
                    # Nested (Name/Value) mapping'te:
                    # - variant_attribute_id KULLANILMAZ, çünkü attribute adı <Name>'den gelir
                    # - direkt attribute adına göre ara/bul/oluştur
                    attribute = self.env['product.attribute'].search([
                        ('name', '=ilike', attr_name),
                    ], limit=1)
                    if not attribute:
                        attribute = self.env['product.attribute'].create({
                            'name': attr_name.strip(),
                            'display_type': 'radio',
                            'create_variant': 'always',
                        })
                        _logger.info(
                            "Varyant attribute otomatik oluşturuldu: %s (XML: %s)",
                            attr_name, attr_value,
                        )
                    attr_key = attribute.id if attribute else f'_raw_{attr_name}'
                    _logger.info("DEBUG   pair: (%s, %s) -> attribute=%s, attr_key=%s",
                                 attr_name, attr_value, attribute.name if attribute else None, attr_key)
                    if attr_key not in variant_attrs:
                        variant_attrs[attr_key] = {
                            'attribute': attribute,
                            'values': [],
                            'xml_path': mapping.xml_path,
                            'xml_attribute_names': [],
                            'resolved': bool(attribute),
                        }
                    elif variant_attrs[attr_key]['values'] and not variant_attrs[attr_key]['xml_attribute_names']:
                        # Flat (value-only) mapping daha önce bu attribute'a değer eklemişse
                        # nested Name/Value çiftleri daha doğru olduğu için onları temizle
                        _logger.info("DEBUG   clearing flat values for attr_key=%s (attribute=%s): old_values=%s, replacing with nested value=%s",
                                     attr_key, attribute.name if attribute else None,
                                     variant_attrs[attr_key]['values'], attr_value)
                        variant_attrs[attr_key]['values'] = []
                        variant_attrs[attr_key]['xml_attribute_names'] = []
                    variant_attrs[attr_key]['values'].append(attr_value)
                    variant_attrs[attr_key]['xml_attribute_names'].append(attr_name)
                _logger.info("DEBUG _apply_variant_overrides: variant_attrs keys after nested: %s", list(variant_attrs.keys()))
                for k, v in variant_attrs.items():
                    _logger.info("DEBUG   key=%s: attribute=%s, values=%s, names=%s",
                                 k, v.get('attribute') and v['attribute'].name, v['values'], v['xml_attribute_names'])
            else:
                attr_id = mapping.variant_attribute_id
                value = None

                # Otomatik Name/Value eşleştirme: mapping'de subpath yoksa,
                # <Attribute> altındaki <Name>/<Value> çiftlerini bul ve attribute
                # adına göre doğru Value'yu seç. Varyant attribute için XML yolu
                # .../Attribute/Value formatındadır.
                if attr_id:
                    parts = rel_path.split('/')
                    # Path .../Name veya .../Value ile bitiyorsa 2 seviye yukarı
                    # (.../Attribute/Name → .../VariantAttributes), yoksa 1 seviye
                    if len(parts) >= 2 and parts[-1].lower() in ('name', 'value'):
                        parent_path = '/'.join(parts[:-2])
                    else:
                        parent_path = '/'.join(parts[:-1])
                    if parent_path:
                        current = v_elem
                        for part in parent_path.split('/'):
                            if current is None:
                                break
                            found = current.find(part)
                            if found is None:
                                for child in current:
                                    if child.tag.lower() == part.lower():
                                        found = child
                                        break
                            current = found
                        if current is not None:
                            for child in list(current):
                                name_el = child.find('Name') or next(
                                    (c for c in child if c.tag.lower() == 'name'), None
                                )
                                value_el = child.find('Value') or next(
                                    (c for c in child if c.tag.lower() == 'value'), None
                                )
                                if (name_el is not None and name_el.text and
                                    value_el is not None and value_el.text and
                                    name_el.text.strip().lower() == attr_id.name.lower()):
                                    value = value_el.text.strip()
                                    break
                if not value:
                    value = self._get_element_value(v_elem, rel_path)
                if value and isinstance(value, str) and value.strip():
                    variant_attrs = data.setdefault('_variant_attrs', {})
                    attr_key = attr_id.id if attr_id else f'_raw_{mapping.xml_path}'
                    if attr_key not in variant_attrs:
                        variant_attrs[attr_key] = {
                            'attribute': attr_id,
                            'values': [],
                            'xml_path': mapping.xml_path,
                            'resolved': bool(attr_id),
                        }
                    variant_attrs[attr_key]['values'].append(value.strip())

    def _parse_wordpress_wxr_xml(self, root):
        """WordPress/WooCommerce WXR exportunu ürün odaklı düzleştir."""
        ns = {
            'wp': 'http://wordpress.org/export/1.2/',
            'content': 'http://purl.org/rss/1.0/modules/content/',
            'excerpt': 'http://wordpress.org/export/1.2/excerpt/',
        }
        channel = root.find('channel')
        items = channel.findall('item') if channel is not None else root.findall('.//item')
        attachment_map = {}

        def _meta_map(item):
            values = {}
            for meta in item.findall('wp:postmeta', ns):
                key = meta.findtext('wp:meta_key', default='', namespaces=ns)
                value = meta.findtext('wp:meta_value', default='', namespaces=ns)
                if key and key not in values:
                    values[key] = value or ''
            return values

        # Önce attachment'ları çöz.
        for item in items:
            post_type = item.findtext('wp:post_type', default='', namespaces=ns)
            if post_type != 'attachment':
                continue
            post_id = item.findtext('wp:post_id', default='', namespaces=ns)
            attachment_url = item.findtext('{http://wordpress.org/export/1.2/}attachment_url', default='') or ''
            if post_id and attachment_url:
                attachment_map[str(post_id).strip()] = attachment_url.strip()

        products = []
        for item in items:
            post_type = item.findtext('wp:post_type', default='', namespaces=ns)
            if post_type != 'product':
                continue

            metas = _meta_map(item)
            categories = []
            brands = []
            attrs = []
            for category in item.findall('category'):
                text = (category.text or '').strip()
                domain = (category.attrib.get('domain') or '').strip()
                if not text:
                    continue
                if domain == 'product_cat' and text not in categories:
                    categories.append(text)
                elif domain == 'product_brand' and text not in brands:
                    brands.append(text)
                elif domain.startswith('pa_'):
                    attrs.append(text)

            thumb_url = attachment_map.get((metas.get('_thumbnail_id') or '').strip(), '')
            gallery_urls = []
            gallery_ids = [gid.strip() for gid in (metas.get('_product_image_gallery') or '').split(',') if gid.strip()]
            for gid in gallery_ids:
                url = attachment_map.get(gid)
                if url and url not in gallery_urls:
                    gallery_urls.append(url)
            if thumb_url:
                gallery_urls = [thumb_url] + [url for url in gallery_urls if url != thumb_url]

            item.set('_WP_TITLE', (item.findtext('title', default='') or '').strip())
            item.set('_WP_CONTENT', (item.findtext('content:encoded', default='', namespaces=ns) or '').strip())
            item.set('_WP_EXCERPT', (item.findtext('excerpt:encoded', default='', namespaces=ns) or '').strip())
            item.set('_WP_SLUG', (item.findtext('wp:post_name', default='', namespaces=ns) or '').strip())
            item.set('_WP_STATUS', (item.findtext('wp:status', default='', namespaces=ns) or '').strip())
            item.set('_WP_SKU', (metas.get('_sku') or '').strip())
            item.set('_WP_PRICE', (metas.get('_price') or metas.get('_regular_price') or '').strip())
            item.set('_WP_REGULAR_PRICE', (metas.get('_regular_price') or '').strip())
            item.set('_WP_STOCK', (metas.get('_stock') or '').strip())
            item.set('_WP_STOCK_STATUS', (metas.get('_stock_status') or '').strip())
            item.set('_WP_CATEGORY', categories[0] if categories else '')
            item.set('_WP_BRAND', brands[0] if brands else '')
            item.set('_WP_ATTR_TERMS', ', '.join(attrs))
            item.set('_WP_IMAGE_GALLERY', ','.join(gallery_urls))
            products.append(item)

        return products

    # ══════════════════════════════════════════════════════════════════════
    # INDEX GRUP / NETEX — Özel XML parse yöntemleri
    # ══════════════════════════════════════════════════════════════════════

    def _parse_indexgrup_xml(self, root):
        """Index Grup / Netex iç içe Katalog XML'ini düzleştir.

        Yapı:
            <INDEXGRUP>
              <KATEGORI KOD="IDX1" TANIM="Bilgisayar">
                <GRUP KOD="1" TANIM="Masaüstü PC">
                  <URUN KOD=".." AD=".." MARKA=".." GLOBALKOD=".." BARCODE="..">
                    <VERGI>KDV18</VERGI>
                    <RESIM>http://...</RESIM>
                    <OZELLIK><OZL TANIM=".." DEGER=".."/></OZELLIK>
                  </URUN>

        Her URUN elementine _KATEGORI ve _GRUP sanal attribute'ları enjekte edilir,
        böylece standart field-mapping mekanizması (@_KATEGORI, @_GRUP) ile okunabilir.
        """
        products = []

        for kategori in root.iter('KATEGORI'):
            kat_tanim = kategori.get('TANIM', '')
            for grup in kategori.iter('GRUP'):
                grup_tanim = grup.get('TANIM', '')
                for urun in grup.iter('URUN'):
                    # Sanal attribute'lar ekle (parent bilgisi)
                    urun.set('_KATEGORI', kat_tanim)
                    urun.set('_GRUP', grup_tanim)
                    products.append(urun)

        # Kategorisiz ürünleri de yakala (düzensiz XML'ler için)
        if not products:
            products = list(root.iter('URUN'))

        return products

    def _fetch_indexgrup_stock_map(self):
        """Index Grup / Netex Stok XML'ini çekip GLOBALKOD → stok miktarı map'i döndürür.

        Stok XML yapısı:
            <INDEXGRUP>
              <URUN KOD="DT.VQEEM.027" STOK="1+" YOL=""/>
        """
        if not self.xml_stock_url:
            return {}

        try:
            original_url = self.xml_url
            self.xml_url = self.xml_stock_url
            xml_content = self._fetch_xml()
            self.xml_url = original_url

            xml_content = re.sub(r'\sxmlns[^"]*"[^"]*"', '', xml_content)
            root = ET.fromstring(xml_content)
            stock_map = {}
            for urun in root.iter('URUN'):
                kod = urun.get('KOD', '').strip()
                stok_raw = urun.get('STOK', '0').strip()
                # "1+", "5+", "10+", "50+", "100+" — sayısal kısmı al
                stok_num = re.sub(r'[^\d]', '', stok_raw)
                try:
                    stock_map[kod] = int(stok_num) if stok_num else 0
                except ValueError:
                    stock_map[kod] = 0
            _logger.info("Index Grup Stok XML: %d ürün stok bilgisi okundu", len(stock_map))
            return stock_map
        except Exception as e:
            _logger.warning("Index Grup Stok XML okunamadı: %s", e)
            return {}

    def _fetch_indexgrup_price_map(self):
        """Index Grup / Netex Fiyat XML'ini çekip GLOBALKOD → fiyat bilgisi map'i döndürür.

        Fiyat XML yapısı:
            <INDEXGRUP>
              <URUN KOD="DT.VQEEM.027" OZEL="123.45" BAYI="130.00" MUSTERI="150.00" PB="TL"/>
        """
        if not self.xml_price_url:
            return {}

        try:
            original_url = self.xml_url
            self.xml_url = self.xml_price_url
            xml_content = self._fetch_xml()
            self.xml_url = original_url

            xml_content = re.sub(r'\sxmlns[^"]*"[^"]*"', '', xml_content)
            root = ET.fromstring(xml_content)
            price_map = {}
            for urun in root.iter('URUN'):
                kod = urun.get('KOD', '').strip()
                ozel = urun.get('OZEL', '').strip()
                bayi = urun.get('BAYI', '').strip()
                musteri = urun.get('MUSTERI', '').strip()
                pb = urun.get('PB', 'TL').strip()
                try:
                    price_map[kod] = {
                        'cost_price': float(ozel.replace(',', '.')) if ozel else 0.0,
                        'dealer_price': float(bayi.replace(',', '.')) if bayi else 0.0,
                        'customer_price': float(musteri.replace(',', '.')) if musteri else 0.0,
                        'currency': pb,
                    }
                except (ValueError, TypeError):
                    pass
            _logger.info("Index Grup Fiyat XML: %d ürün fiyat bilgisi okundu", len(price_map))
            return price_map
        except Exception as e:
            _logger.warning("Index Grup Fiyat XML okunamadı: %s", e)
            return {}

    def _get_element_value(self, element, path):
        """Element içinden değer al (nested path desteği)"""
        if not path:
            return None

        # Path'i parçala (örn: "Images/Image/Url")
        parts = path.split('/')
        current = element

        for i, part in enumerate(parts):
            if current is None:
                return None

            # Attribute kontrolü (@attr)
            if part.startswith('@'):
                return current.get(part[1:])

            # Son parça mı kontrol et (çoklu değer için)
            is_last_part = (i == len(parts) - 1)

            # Child element bul
            found = current.find(part)
            if found is None:
                # Küçük/büyük harf duyarsız ara
                for child in current:
                    if child.tag.lower() == part.lower():
                        found = child
                        break

            current = found

        if current is not None:
            return current.text

        return None

    def _get_nested_variant_attributes(self, element, mapping, override_path=None):
        """İç içe <Attribute> elementlerinden (Name/Value) çiftlerini topla

        Örn: xml_path="Variants/Variant/VariantAttributes/Attribute",
             name_subpath="Name", value_subpath="Value"
        verilen bir element için tüm <Attribute> altındaki
        (Name, Value) çiftlerini döndürür.

        override_path varsa mapping.xml_path yerine bu kullanılır (v_elem'den
        göreceli okuma için).

        Returns:
            [(name_str, value_str), ...]
        """
        if not mapping.variant_name_subpath or not mapping.variant_value_subpath:
            return []

        xml_path = override_path or mapping.xml_path
        parts = xml_path.split('/')
        if len(parts) < 2:
            return []

        # Son parça iterasyon elementi, öncesi parent
        iter_tag = parts[-1]
        parent_parts = parts[:-1]

        current = element
        for part in parent_parts:
            if current is None:
                return []
            found = current.find(part)
            if found is None:
                for child in current:
                    if child.tag.lower() == part.lower():
                        found = child
                        break
            current = found

        if current is None:
            return []

        # Parent altındaki iter_tag'a uyan TÜM elementleri topla
        results = []
        children = list(current)
        _logger.info("DEBUG _get_nested_variant_attributes: current=<%s>, children=%d, xml_path=%s, override_path=%s",
                      current.tag if current is not None else 'None', len(children), xml_path, override_path)
        for ci, child in enumerate(children):
            _logger.info("DEBUG   child[%d]: tag=%s, attrib=%s, text=%s", ci, child.tag, child.attrib, child.text)
            if child.tag.lower() != iter_tag.lower():
                _logger.info("DEBUG   skipping child[%d] tag=%s != expected=%s", ci, child.tag, iter_tag)
                continue

            name_el = child.find(mapping.variant_name_subpath)
            if name_el is None:
                for c in child:
                    if c.tag.lower() == mapping.variant_name_subpath.lower():
                        name_el = c
                        break
            value_el = child.find(mapping.variant_value_subpath)
            if value_el is None:
                for c in child:
                    if c.tag.lower() == mapping.variant_value_subpath.lower():
                        value_el = c
                        break
            if name_el is not None and name_el.text and value_el is not None and value_el.text:
                results.append((name_el.text.strip(), value_el.text.strip()))
                _logger.info("DEBUG   extracted pair[%d]: name_el.text='%s' value_el.text='%s'",
                             ci, name_el.text.strip(), value_el.text.strip())
            else:
                _logger.info("DEBUG   skipped pair[%d]: name_el=%s(%s) value_el=%s(%s)",
                             ci,
                             'OK' if name_el is not None else 'NONE',
                             name_el.text if name_el is not None and name_el.text else 'EMPTY',
                             'OK' if value_el is not None else 'NONE',
                             value_el.text if value_el is not None and value_el.text else 'EMPTY')

        _logger.info("DEBUG _get_nested_variant_attributes: returning %d pairs: %s", len(results), results)
        return results

    def _get_element_values(self, element, path):
        """Element içinden TÜM değerleri al (çoklu görsel için)"""
        if not path:
            return []

        values = []
        parts = path.split('/')

        # İlk parçaya kadar git (parent element)
        current = element
        for part in parts[:-1]:
            if current is None:
                return []
            found = current.find(part)
            if found is None:
                for child in current:
                    if child.tag.lower() == part.lower():
                        found = child
                        break
            current = found

        # Son parçadaki TÜM elementleri bul
        if current is not None and len(parts) > 0:
            last_part = parts[-1]
            for child in current:
                if child.tag.lower() == last_part.lower():
                    if child.text:
                        values.append(child.text.strip())

        return values

    def _extract_product_data(self, element, strict=False):
        """XML elementinden ürün verilerini çıkar

        Args:
            element: XML element
            strict: True ise sadece field mapping'de eşleşen alanları döndürür,
                    fallback/otomatik alanları atlar (önizleme için).
        """
        self.ensure_one()

        data = {}
        image_values = []
        variant_attrs = {}

        for mapping in self.field_mapping_ids:
            # İç içe varyant yapısı (<VariantAttributes>/<Attribute> Name/Value)
            if mapping.odoo_field == 'variant_attribute' and mapping.variant_name_subpath and mapping.variant_value_subpath:
                # Path 'Variants/Variant/...' ile başlıyorsa bu element'ten okuma
                # (yalnızca ilk varyantı bulur). Asıl okuma _apply_variant_overrides
                # içinde v_elem'den yapılır.
                xml_path_lower = mapping.xml_path.lower()
                _logger.info("DEBUG _extract_product_data: strict=%s, nested variant mapping found, xml_path_lower=%s", strict, xml_path_lower)
                if xml_path_lower.startswith('variants/variant/'):
                    _logger.info("DEBUG _extract_product_data: SKIPPING nested variant from product element (will be read from v_elem in _apply_variant_overrides)")
                    continue
                pairs = self._get_nested_variant_attributes(element, mapping)
                for attr_name, attr_value in pairs:
                    attribute = None
                    if mapping.variant_attribute_id:
                        attribute = mapping.variant_attribute_id
                    else:
                        mapping_rec = self.env['xml.variant.mapping'].find_mapping(
                            self.id, attr_value, xml_attribute_name=attr_name
                        )
                        if mapping_rec and mapping_rec.attribute_id:
                            attribute = mapping_rec.attribute_id
                        else:
                            attribute = self.env['product.attribute'].search([
                                ('name', '=ilike', attr_name),
                            ], limit=1)
                            if not attribute:
                                attribute = self.env['product.attribute'].create({
                                    'name': attr_name.strip(),
                                    'display_type': 'radio',
                                    'create_variant': 'always',
                                })
                                _logger.info(
                                    "Varyant attribute otomatik oluşturuldu: %s (XML: %s)",
                                    attr_name, attr_value,
                                )
                    # Her zaman kaydet (attribute bulunamadıysa yeni oluşturuldu)
                    attr_key = attribute.id if attribute else f'_raw_{attr_name}'
                    if attr_key not in variant_attrs:
                        variant_attrs[attr_key] = {
                            'attribute': attribute,
                            'values': [],
                            'xml_path': mapping.xml_path,
                            'xml_attribute_names': [],
                            'resolved': bool(attribute),
                        }
                    variant_attrs[attr_key]['values'].append(attr_value)
                    variant_attrs[attr_key]['xml_attribute_names'].append(attr_name)
                continue

            value = self._get_element_value(element, mapping.xml_path)

            if value:
                if mapping.transform:
                    value = mapping.apply_transform(value)

                if mapping.odoo_field in ('image', 'image2', 'image3', 'image4'):
                    if isinstance(value, str):
                        for candidate in value.split(','):
                            candidate = candidate.strip()
                            if candidate and candidate.startswith('http'):
                                image_values.append(candidate)
                    continue

                elif mapping.odoo_field == 'images':
                    all_images = self._get_element_values(element, mapping.xml_path)
                    for candidate in all_images:
                        if candidate and str(candidate).startswith('http'):
                            image_values.append(str(candidate).strip())

                elif mapping.odoo_field == 'variant_attribute':
                    # Flat (basit) varyant: direkt XML yoluyla değer oku
                    # Path 'Variants/Variant/...' ile başlıyorsa atla,
                    # _apply_variant_overrides v_elem'den doğru değeri okur.
                    if mapping.xml_path.lower().startswith('variants/variant/'):
                        continue
                    if isinstance(value, str) and value.strip():
                        attr_id = mapping.variant_attribute_id
                        attr_key = attr_id.id if attr_id else f'_raw_{mapping.xml_path}'
                        if attr_key not in variant_attrs:
                            variant_attrs[attr_key] = {
                                'attribute': attr_id,
                                'values': [],
                                'xml_path': mapping.xml_path,
                                'resolved': bool(attr_id),
                            }
                        variant_attrs[attr_key]['values'].append(value.strip())

                else:
                    data[mapping.odoo_field] = value

        if variant_attrs:
            data['_variant_attrs'] = variant_attrs

        if strict:
            return data

        # Mapping'e eklenmemiş olsa bile standart harici kimlik alanlarını otomatik oku.
        fallback_fields = {
            'name': ['ProductName', 'product_name', 'Name', 'name', 'Title', 'title'],
            'external_product_id': ['ExternalProductId', 'ProductId'],
            'source_stock_id': ['SourceStockId', 'StockId'],
            'usage_class': ['UsageClass', 'ProductUsageClass'],
            'variant_group': ['VariantGroup', 'VariantKey', 'MainCode'],
        }
        for key, paths in fallback_fields.items():
            if data.get(key):
                continue
            for path in paths:
                value = self._get_element_value(element, path)
                if value:
                    data[key] = value
                    break

        # Görselleri birleştir: ana görsel ve ek görseller
        if image_values:
            # Tekrarlı URL'leri temizle ve bozukları at
            cleaned_images = []
            for img in image_values:
                if img and img.startswith('http') and img not in cleaned_images:
                    cleaned_images.append(img)
            if cleaned_images:
                data['image'] = cleaned_images[0]
                if len(cleaned_images) > 1:
                    data['extra_images'] = cleaned_images[1:]

        # Tahtakale/Google benzeri feedlerde ek görselleri de topla
        # (xml templateinde farklı alanlarla gelebilir)
        extra_image_paths = [
            'additional_image_link1',
            'additional_image_link2',
            'additional_image_link3',
            'additional_image_link4',
            'extra_image_1',
            'extra_image_2',
        ]
        if self.xml_template == 'akinsoft':
            extra_image_paths.extend([f'GORSEL{i}' for i in range(1, 11)])
        current_image_list = []
        if data.get('image'):
            current_image_list.append(data['image'])
        if data.get('extra_images'):
            current_image_list.extend(data['extra_images'])

        for img_path in extra_image_paths:
            extra_img = self._get_element_value(element, img_path)
            if extra_img:
                extra_img = extra_img.strip()
                if extra_img and extra_img.startswith('http') and extra_img not in current_image_list:
                    current_image_list.append(extra_img)

        if current_image_list:
            # Ana görsel + ek görselleri tekilleştirilmiş olarak güncelle
            data['image'] = current_image_list[0]
            if len(current_image_list) > 1:
                data['extra_images'] = current_image_list[1:]

        # Eğer image hala boşsa alternatif yolları dene
        if not data.get('image'):
            # Alternatif görsel yollarını dene
            image_paths = [
                'images/img_item', 'Images/Image/Path', 'Images/Image/Url', 'Images/Image',
                'images/image/url', 'images/image', 'Image', 'image',
                'picture1', 'picture', 'photo', 'img', 'ImageUrl', 'imageUrl',
                'MainImage', 'mainimage', 'PrimaryImage', 'ProductImage',
            ]
            if self.xml_template == 'akinsoft':
                image_paths.extend([f'GORSEL{i}' for i in range(1, 11)])
            for path in image_paths:
                # Önce tekli, sonra çoklu dene
                img_val = self._get_element_value(element, path)
                if img_val and img_val.startswith('http'):
                    data['image'] = img_val
                    break
                # Çoklu görsel dene
                all_imgs = self._get_element_values(element, path)
                if all_imgs:
                    data['image'] = all_imgs[0]
                    if len(all_imgs) > 1:
                        data['extra_images'] = all_imgs[1:]
                    break

        # Açıklama alternatiflerini dene
        if not data.get('description'):
            desc_paths = [
                'detail', 'Detail', 'Description', 'description', 'Details', 'details',
                'LongDescription', 'longdescription', 'ProductDescription',
                'content', 'Content', 'body', 'Body', 'text', 'Text',
                'Aciklama', 'aciklama', 'detay', 'Detay',
            ]
            for path in desc_paths:
                desc_val = self._get_element_value(element, path)
                if desc_val and len(desc_val) > 10:
                    data['description'] = desc_val
                    break

        if self.xml_template == 'google_rss':
            # Google RSS kaynaklarında SKU bazen model_number yerine id/barcode'da gelir.
            if not data.get('sku'):
                for path in ('model_number', 'id', 'barcode'):
                    value = self._get_element_value(element, path)
                    if value:
                        data['sku'] = value.strip()
                        break

            # Tekrarlanan category/product_type alanlarından en detaylı olanı seç.
            category_values = []
            for path in ('category', 'product_type'):
                category_values.extend(self._get_element_values(element, path))
                value = self._get_element_value(element, path)
                if value:
                    category_values.append(value)
            cleaned_categories = []
            for value in category_values:
                value = (value or '').strip()
                if value and value not in cleaned_categories:
                    cleaned_categories.append(value)
            if cleaned_categories:
                cleaned_categories.sort(key=lambda item: ('>' not in item, -len(item)))
                data['category'] = cleaned_categories[0]
                if len(cleaned_categories) > 1 and not data.get('extra1'):
                    data['extra1'] = cleaned_categories[1]

            # quantity boşsa availability bilgisinden kaba stok üret.
            if not data.get('stock'):
                availability = (self._get_element_value(element, 'availability') or '').strip().lower()
                if availability:
                    data['stock'] = '0' if 'out' in availability else '1'

        # ═══════════════════════════════════════════════════════════
        # INDEX GRUP / NETEX — Özel veri çıkarma
        # ═══════════════════════════════════════════════════════════
        if self.xml_template in ('indexgrup', 'netex'):
            # KDV oranını VERGi etiketinden çıkar: "KDV18" → "18"
            tax_raw = data.get('tax', '')
            if tax_raw:
                tax_num = re.sub(r'[^\d]', '', tax_raw)
                if tax_num:
                    data['tax'] = tax_num

            # Kategori yolunu "Kategori > Grup" olarak birleştir
            kat = data.get('category', '')
            grp = data.pop('extra1', '') if data.get('extra1') else ''
            if kat and grp:
                data['category'] = '%s > %s' % (kat, grp)
            elif grp:
                data['category'] = grp

            # OZELLIK/OZL etiketlerinden ek bilgileri çıkar
            ozellik_el = element.find('OZELLIK')
            if ozellik_el is not None:
                specs = []
                for ozl in ozellik_el.findall('OZL'):
                    tanim = ozl.get('TANIM', '').strip()
                    deger = ozl.get('DEGER', '').strip()
                    if tanim and deger:
                        specs.append('%s: %s' % (tanim, deger))
                if specs and not data.get('description'):
                    data['description'] = '\n'.join(specs)

            # RESIM_DETAY varsa ek görsel olarak ekle
            resim_detay = element.find('RESIM_DETAY')
            if resim_detay is not None and resim_detay.text:
                detail_url = resim_detay.text.strip()
                if detail_url.startswith('http'):
                    if 'extra_images' not in data:
                        data['extra_images'] = []
                    if detail_url not in data.get('extra_images', []):
                        data['extra_images'].append(detail_url)

        return data

    def _should_skip_product_data(self, data):
        """İçe aktarım öncesi ürün bazlı atlama kuralları."""
        category = (data.get('category') or '').strip().upper()
        extra1 = (data.get('extra1') or '').strip().upper()
        combined = ' '.join([category, extra1])
        if 'YEDEK PARÇA' in combined or 'YEDEK PARCA' in combined:
            return True, _('Yedek parçalar kategorisi atlandı')
        return False, False

    def _classify_usage(self, data):
        """XML ürününü ticari / iç kullanım / hizmet sınıfına ayır."""
        explicit_value = (data.get('usage_class') or '').strip().lower()
        explicit_map = {
            'commercial': 'commercial',
            'ticari': 'commercial',
            'operational': 'operational',
            'operasyon': 'operational',
            'sarf': 'operational',
            'internal': 'internal',
            'company_internal': 'internal',
            'ic_kullanim': 'internal',
            'service': 'service',
            'expense': 'service',
            'gider': 'service',
        }
        if explicit_value in explicit_map:
            return explicit_map[explicit_value]

        haystack = ' '.join([
            str(data.get('name') or ''),
            str(data.get('category') or ''),
            str(data.get('extra1') or ''),
            str(data.get('description') or ''),
        ]).lower()

        service_keywords = (
            ' hizmet', 'gider', 'masraf', 'nakliye', 'kargo', 'akaryakit',
            'telekom', 'seyahat', 'abonelik', 'komisyon', 'premium', 'kep',
        )
        operational_keywords = (
            'ambalaj', 'karton', 'bant', 'etiket', 'paketleme', 'koli',
        )
        internal_keywords = (
            'demirbas', 'demirbaş', 'ofis', 'raf', 'ates olcer', 'ateş ölçer',
        )

        if any(token in haystack for token in service_keywords):
            return 'service'
        if any(token in haystack for token in operational_keywords):
            return 'operational'
        if any(token in haystack for token in internal_keywords):
            return 'internal'
        return 'commercial'

    def _normalized_product_defaults(self, data, protect_core=False):
        """Online Odoo ürün modeline yakın temel ürün ayarlarını üret."""
        usage_class = self._classify_usage(data)
        vals = {
            'xml_usage_class': usage_class,
        }

        if data.get('external_product_id'):
            vals['xml_external_id'] = str(data['external_product_id']).strip()
        if data.get('source_stock_id'):
            vals['xml_stock_id'] = str(data['source_stock_id']).strip()
        if data.get('variant_group'):
            vals['xml_variant_group'] = str(data['variant_group']).strip()

        if protect_core:
            return vals

        if usage_class == 'commercial':
            vals.update({
                'type': 'consu',
                'sale_ok': True,
                'purchase_ok': True,
                'invoice_policy': 'order',
                'purchase_method': 'receive',
            })
        elif usage_class == 'operational':
            vals.update({
                'type': 'consu',
                'sale_ok': False,
                'purchase_ok': True,
                'invoice_policy': 'order',
                'purchase_method': 'receive',
            })
        elif usage_class == 'internal':
            vals.update({
                'type': 'consu',
                'sale_ok': False,
                'purchase_ok': True,
                'invoice_policy': 'order',
                'purchase_method': 'receive',
            })
        else:
            vals.update({
                'type': 'service',
                'sale_ok': False,
                'purchase_ok': True,
                'invoice_policy': 'order',
                'purchase_method': 'purchase',
                'service_type': 'manual',
            })

        return vals

    def _default_category_for_usage(self, usage_class):
        """Online Odoo'daki ürün düzenine göre varsayılan kategori döndür."""
        self.ensure_one()
        category_names = {
            'service': 'Services / Masraf Kalemleri',
            'operational': 'Ambalj',
            'internal': 'Services / Masraf Kalemleri',
            'commercial': 'Özel Ürünler',
        }
        target_name = category_names.get(usage_class or 'commercial', 'Özel Ürünler')
        Category = self.env['product.category'].with_context(active_test=False)
        return Category.search([('complete_name', '=', target_name)], limit=1) or Category.search([('name', '=', target_name)], limit=1)

    def _product_has_invoice_links(self, product):
        """Muhasebe kayıtlarına bağlı ürünlerde kimlik alanlarını yerinden oynatma."""
        self.ensure_one()
        if not product or not product.exists():
            return False
        return bool(self.env['account.move.line'].search_count([
            ('product_id.product_tmpl_id', '=', product.id),
            ('parent_state', '=', 'posted'),
        ]))

    def _product_has_operational_links(self, product):
        """Stok hareketi olan ürünleri de yıkıcı işlemlerden koru."""
        self.ensure_one()
        if not product or not product.exists():
            return False
        return bool(self.env['stock.move'].search_count([
            ('product_id.product_tmpl_id', '=', product.id),
            ('state', '=', 'done'),
        ]))

    def _is_reference_locked_product(self, product):
        self.ensure_one()
        return self._product_has_invoice_links(product) or self._product_has_operational_links(product)

    def _can_rebind_product_identity(self, product, data):
        """Yanlis urun eslesmesinde ad/kod/xml kimligini bozmamaya calis."""
        self.ensure_one()
        if not product or not product.exists():
            return False

        incoming_external = str(data.get('external_product_id') or '').strip()
        incoming_stock = str(data.get('source_stock_id') or '').strip()
        incoming_sku = str(data.get('sku') or '').strip()
        incoming_name = str(data.get('name') or '').strip()
        incoming_barcode = str(data.get('barcode') or '').strip()
        base_sku, _variant = self._extract_base_and_variant(incoming_sku)

        if incoming_external and product.xml_external_id and product.xml_external_id != incoming_external:
            return False
        if incoming_stock and product.xml_stock_id and product.xml_stock_id != incoming_stock:
            return False

        if self._is_reference_locked_product(product):
            return False

        if product.default_code and base_sku and product.default_code != base_sku:
            return False

        if incoming_barcode and len(product.product_variant_ids) == 1:
            local_barcode = (product.product_variant_ids.barcode or '').strip()
            if local_barcode and local_barcode != incoming_barcode:
                return False

        if incoming_name and product.name:
            name_ratio = SequenceMatcher(None, incoming_name.lower(), product.name.lower()).ratio() * 100
            if name_ratio < 80 and not (base_sku and product.default_code == base_sku):
                return False

        return True

    def _download_image(self, url):
        """URL'den görsel indir ve base64 olarak döndür"""
        if not url:
            return None

        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'image/*,*/*',
            }
            response = requests.get(url, headers=headers, timeout=30, stream=True)
            response.raise_for_status()

            # İçerik tipi kontrolü
            content_type = response.headers.get('Content-Type', '')
            if not any(t in content_type for t in ['image', 'octet-stream']):
                _logger.warning(f"Geçersiz görsel tipi: {content_type} - {url}")
                return None

            # Boyut kontrolü (max 10MB)
            content_length = response.headers.get('Content-Length')
            if content_length and int(content_length) > 10 * 1024 * 1024:
                _logger.warning(f"Görsel çok büyük: {content_length} bytes - {url}")
                return None

            # Base64'e çevir
            image_data = base64.b64encode(response.content).decode('utf-8')

            _logger.debug(f"Görsel indirildi: {url}")
            return image_data

        except requests.exceptions.RequestException as e:
            _logger.warning(f"Görsel indirilemedi: {url} - {e}")
            return None
        except Exception as e:
            _logger.warning(f"Görsel işleme hatası: {url} - {e}")
            return None

    def _clean_html(self, html_content):
        """HTML içeriğini temizle ve düzgün formatla"""
        if not html_content:
            return ''

        import re
        from html import unescape

        # HTML entity'leri decode et
        html_content = unescape(html_content)

        # Script ve style etiketlerini tamamen kaldır
        html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)

        # <BR> etiketlerini satır sonuna çevir
        html_content = re.sub(r'<br\s*/?>', '\n', html_content, flags=re.IGNORECASE)

        # Boş span/div etiketlerini kaldır
        html_content = re.sub(r'<span[^>]*>\s*</span>', '', html_content, flags=re.IGNORECASE)
        html_content = re.sub(r'<div[^>]*>\s*</div>', '', html_content, flags=re.IGNORECASE)

        # ID'siz, class'sız, boş div/span'leri kaldır
        html_content = re.sub(r'<div>\s*', '', html_content, flags=re.IGNORECASE)
        html_content = re.sub(r'\s*</div>', '', html_content, flags=re.IGNORECASE)
        html_content = re.sub(r'<span>\s*', '', html_content, flags=re.IGNORECASE)
        html_content = re.sub(r'\s*</span>', '', html_content, flags=re.IGNORECASE)

        # Inline style ve event handler'ları kaldır
        html_content = re.sub(r'\s+on\w+="[^"]*"', '', html_content, flags=re.IGNORECASE)
        html_content = re.sub(r'\s+style="[^"]*"', '', html_content, flags=re.IGNORECASE)

        # Gereksiz attribute'ları kaldır (sayısal ID'ler vs)
        html_content = re.sub(r'\s+\d{15,}', '', html_content)

        # <UL> ve <LI> etiketlerini temizle
        html_content = re.sub(r'<ul[^>]*>', '\n', html_content, flags=re.IGNORECASE)
        html_content = re.sub(r'</ul>', '', html_content, flags=re.IGNORECASE)
        html_content = re.sub(r'<li[^>]*>', '• ', html_content, flags=re.IGNORECASE)
        html_content = re.sub(r'</li>', '\n', html_content, flags=re.IGNORECASE)

        # Birden fazla boşluğu tekile indir
        html_content = re.sub(r' {2,}', ' ', html_content)

        # Birden fazla satır sonunu ikiye indir
        html_content = re.sub(r'\n{3,}', '\n\n', html_content)

        html_content = html_content.strip()

        return html_content

    def _extract_all_images(self, element):
        """XML elementinden tüm görsel URL'lerini çıkar"""
        images = []

        # Farklı görsel path'lerini dene
        image_paths = [
            './/Images/Image/Path', './/Images/Image/Url', './/Images/Image',
            './/images/image/url', './/images/image',
            './/Picture', './/picture', './/Photo', './/photo',
            './/image', './/Image', './/img', './/Img',
            './picture1', './picture2', './picture3', './picture4', './picture5',
        ]
        if self.xml_template == 'akinsoft':
            image_paths.extend([f'./GORSEL{i}' for i in range(1, 11)])

        for path in image_paths:
            found = element.findall(path)
            for img_elem in found:
                url = img_elem.text if img_elem.text else img_elem.get('url') or img_elem.get('src')
                if url and url.startswith('http') and url not in images:
                    images.append(url)

        return images

    # ══════════════════════════════════════════════════════════════════════════
    # PRICE CALCULATION
    # ══════════════════════════════════════════════════════════════════════════

    def _calculate_sale_price(self, cost_price):
        """Tedarikçi fiyatından satış fiyatı hesapla"""
        self.ensure_one()

        if not cost_price:
            return 0.0

        cost = float(cost_price)
        sale_price = cost

        # Markup uygula
        if self.price_markup_type in ('percent', 'both'):
            sale_price = cost * (1 + self.price_markup_percent / 100)

        if self.price_markup_type in ('fixed', 'both'):
            sale_price += self.price_markup_fixed

        # Yuvarlama
        if self.price_round:
            if self.price_round_method == '99':
                sale_price = int(sale_price) + 0.99
            elif self.price_round_method == '90':
                sale_price = int(sale_price) + 0.90
            elif self.price_round_method == '00':
                sale_price = round(sale_price)

        return sale_price

    def _find_tax_by_value(self, tax_value):
        """XML'den gelen KDV değerinden Odoo satış vergisini bul.
        '18', '18%', '%18', 'KDV 18', '0.18' gibi formatları destekler.
        """
        if not tax_value:
            return False
        tax_str = str(tax_value).strip()
        match = re.search(r'\d+(?:[.,]\d+)?', tax_str)
        if not match:
            return False
        rate = float(match.group().replace(',', '.'))
        # '0.18' gibi ondalık format → yüzdeye çevir
        if rate < 1:
            rate = rate * 100
        tax = self.env['account.tax'].search([
            ('type_tax_use', '=', 'sale'),
            ('amount', '=', rate),
            ('active', '=', True),
        ], limit=1)
        if tax:
            _logger.debug("KDV eşleşti: %s → %s (%%%.0f)", tax_value, tax.name, rate)
        else:
            _logger.debug("KDV bulunamadı: %s (oran: %.0f)", tax_value, rate)
        return tax

    # ══════════════════════════════════════════════════════════════════════════
    # CATEGORY MATCHING
    # ══════════════════════════════════════════════════════════════════════════

    def _apply_category_mapping(self, category_name, subcategory_name=None):
        """
        Kategori eşleştirmesi uygula.

        Önce manuel eşleştirmeleri kontrol eder, bulunamazsa otomatik eşleştirme yapar.

        Returns:
            dict: {
                'categ_id': product.category ID veya False,
                'public_categ_ids': [(6, 0, [IDs])] veya False
            }
        """
        self.ensure_one()

        result = {
            'categ_id': False,
            'public_categ_ids': False,
        }

        if not category_name:
            if self.default_category_id:
                result['categ_id'] = self.default_category_id.id
            return result

        # Tam kategori yolunu oluştur
        full_category_path = str(category_name).strip()
        if subcategory_name:
            separator = self.category_separator or ' > '
            full_category_path = f"{full_category_path}{separator}{str(subcategory_name).strip()}"

        # 1. Manuel eşleştirmeleri kontrol et
        CategoryMapping = self.env['xml.category.mapping']
        mapping = CategoryMapping.find_mapping(self.id, full_category_path)

        # Alt kategori olmadan da dene
        if not mapping and subcategory_name:
            mapping = CategoryMapping.find_mapping(self.id, str(category_name).strip())

        if mapping:
            _logger.info(f"Kategori eşleştirmesi bulundu: '{full_category_path}' → "
                        f"Odoo: {mapping.odoo_category_id.name if mapping.odoo_category_id else 'Yok'}, "
                        f"E-Ticaret: {[c.name for c in mapping.ecommerce_category_ids]}")

            if mapping.odoo_category_id:
                result['categ_id'] = mapping.odoo_category_id.id

            if mapping.ecommerce_category_ids:
                result['public_categ_ids'] = [(6, 0, mapping.ecommerce_category_ids.ids)]

            # Eğer Odoo kategorisi yoksa varsayılanı kullan
            if not result['categ_id'] and self.default_category_id:
                result['categ_id'] = self.default_category_id.id

            return result

        # 2. Manuel eşleştirme yoksa otomatik eşleştirme yap
        category = self._find_or_create_category(category_name, subcategory_name)
        if category:
            result['categ_id'] = category.id

        return result

    def _find_or_create_category(self, category_name, subcategory_name=None):
        """Kategoriyi bul veya oluştur (otomatik eşleştirme)"""
        self.ensure_one()

        if not category_name:
            return self.default_category_id or None

        Category = self.env['product.category']
        category_name = str(category_name).strip()

        # 1. Tam eşleşme ara (büyük/küçük harf duyarsız)
        category = Category.search([
            ('name', '=ilike', category_name)
        ], limit=1)

        if category:
            # Alt kategori varsa onunla devam et
            if subcategory_name:
                subcategory_name = str(subcategory_name).strip()
                subcategory = Category.search([
                    ('name', '=ilike', subcategory_name),
                    ('parent_id', '=', category.id)
                ], limit=1)

                if subcategory:
                    return subcategory
                elif self.auto_create_category:
                    # Alt kategoriyi oluştur
                    return Category.create({
                        'name': subcategory_name,
                        'parent_id': category.id,
                    })
                else:
                    return category  # Alt kategori oluşturulamıyor, ana kategori döndür
            return category

        # 2. Benzer kategori ara (kısmi eşleşme)
        similar = Category.search([
            ('name', 'ilike', category_name)
        ], limit=1)

        if similar:
            _logger.info(f"Benzer kategori bulundu: '{category_name}' → '{similar.name}'")
            if subcategory_name:
                subcategory_name = str(subcategory_name).strip()
                subcategory = Category.search([
                    ('name', '=ilike', subcategory_name),
                    ('parent_id', '=', similar.id)
                ], limit=1)

                if subcategory:
                    return subcategory
                elif self.auto_create_category:
                    return Category.create({
                        'name': subcategory_name,
                        'parent_id': similar.id,
                    })
                else:
                    return similar
            return similar

        # 3. Kategori bulunamadı
        if not self.auto_create_category:
            # Otomatik oluşturma kapalı, varsayılan kategori döndür
            _logger.info(f"Kategori bulunamadı (otomatik oluşturma kapalı): {category_name}")
            return self.default_category_id or None

        # Yeni oluştur
        _logger.info(f"Yeni kategori oluşturuluyor: {category_name}")

        # Ana kategoriyi oluştur
        parent_category = Category.create({
            'name': category_name,
        })

        # Alt kategori varsa onu da oluştur
        if subcategory_name:
            subcategory_name = str(subcategory_name).strip()
            return Category.create({
                'name': subcategory_name,
                'parent_id': parent_category.id,
            })

        return parent_category

    # ══════════════════════════════════════════════════════════════════════════
    # PRODUCT MATCHING
    # ══════════════════════════════════════════════════════════════════════════

    def _find_existing_product(self, data):
        """Mevcut ürünü bul - Önce Odoo standart _retrieve_product, sonra kaynak özel kurallar"""
        self.ensure_one()
        ProductT = self.env['product.template'].with_context(active_test=False)
        ProductP = self.env['product.product'].with_context(active_test=False)

        sku = str(data.get('sku', '')).strip() if data.get('sku') else ''
        sku_prefix = sku.split()[0] if sku else ''

        # 0. xml_variant_group ile bul (varyant gruplaması yapan feed'ler için öncelikli)
        variant_group = str(data.get('variant_group', '')).strip() if data.get('variant_group') else ''
        if variant_group:
            product = ProductT.search([('xml_variant_group', '=', variant_group)], limit=1)
            if product:
                return product, 'variant_group'

        external_product_id = str(data.get('external_product_id', '')).strip() if data.get('external_product_id') else ''
        if external_product_id:
            product = ProductT.search([('xml_external_id', '=', external_product_id)], limit=1)
            if product:
                return product, 'external_product_id'

        source_stock_id = str(data.get('source_stock_id', '')).strip() if data.get('source_stock_id') else ''
        if source_stock_id:
            product = ProductT.search([('xml_stock_id', '=', source_stock_id)], limit=1)
            if product:
                return product, 'source_stock_id'

        # 0. Odoo standart _retrieve_product (Nilvera/UBL ile aynı mantık) — öncelikli
        product_vals = {}
        if data.get('barcode'):
            product_vals['barcode'] = str(data['barcode']).strip()
        if sku:
            product_vals['default_code'] = sku
        if data.get('name'):
            product_vals['name'] = str(data['name']).strip().split('\n', 1)[0]
        if product_vals:
            product = ProductP._retrieve_product(
                company=self.env.company,
                **product_vals
            )
            if product and product.product_tmpl_id:
                if self._can_rebind_product_identity(product.product_tmpl_id, data):
                    return product.product_tmpl_id, 'odoo_standard'

        # 1. SKU Prefix (ilk kelime) ile eşleştir
        if self.match_by_sku_prefix and sku_prefix:
            # Önce tam prefix eşleşmesi
            product = ProductT.search([
                ('default_code', '=like', sku_prefix + '%')
            ], limit=1)
            if product and self._can_rebind_product_identity(product, data):
                return product, 'sku_prefix'

        # 2. Barkod ile eşleştir
        if self.match_by_barcode and data.get('barcode'):
            barcode = str(data['barcode']).strip()
            if barcode:
                # 2a. Önce product.product üzerinden (aktif+arşiv dahil) barkod ara
                variant = ProductP.search([('barcode', '=', barcode)], limit=1)
                if variant and variant.product_tmpl_id:
                    return variant.product_tmpl_id, 'barcode'

                # 2b. Barkod ürün adında olabilir (örn: "8699931326048-PROPODS3")
                product = ProductT.search([('name', 'ilike', barcode)], limit=1)
                if product and self._can_rebind_product_identity(product, data):
                    return product, 'barcode_in_name'

                # 2c. Barkod SKU'da olabilir
                product = ProductT.search([('default_code', '=', barcode)], limit=1)
                if product and self._can_rebind_product_identity(product, data):
                    return product, 'barcode_as_sku'

        # 3. SKU/Ürün kodu ile tam eşleştir
        if self.match_by_sku and sku:
            product = ProductT.search([('default_code', '=', sku)], limit=1)
            if product and self._can_rebind_product_identity(product, data):
                return product, 'sku_exact'

        # 4. Açıklama ile eşleştir
        if self.match_by_description and data.get('description'):
            description = str(data['description']).strip().lower()
            if description and len(description) > 10:
                all_products = ProductT.search([('description_sale', '!=', False)])
                for prod in all_products:
                    if not prod.description_sale:
                        continue
                    prod_desc = prod.description_sale.lower()

                    # 4a. Açıklamada ürün kodu var mı?
                    if sku_prefix and sku_prefix.lower() in prod_desc:
                        if self._can_rebind_product_identity(prod, data):
                            return prod, 'description_has_sku'

                    # 4b. Açıklama benzerliği kontrolü
                    ratio = SequenceMatcher(None, description[:200], prod_desc[:200]).ratio() * 100
                    if ratio >= self.description_match_ratio:
                        if self._can_rebind_product_identity(prod, data):
                            return prod, f'description_similar_{int(ratio)}%'

        # 5. İsim benzerliği ile eşleştir
        if self.match_by_name and data.get('name'):
            name = str(data['name']).strip()
            if name:
                # Önce tam eşleşme
                product = ProductT.search([('name', '=ilike', name)], limit=1)
                if product and self._can_rebind_product_identity(product, data):
                    return product, 'name_exact'

                # 5a. Parantezden varyant modu - ana isim ile ara
                if self.variant_from_parentheses:
                    base_name, variant_name = self._extract_base_and_variant(name)
                    if base_name and variant_name:
                        # Ana isim ile tam eşleşme ara
                        product = ProductT.search([('name', '=ilike', base_name)], limit=1)
                        if product and self._can_rebind_product_identity(product, data):
                            return product, 'base_name_exact'

                        # Ana isim ile benzerlik ara
                        all_products = ProductT.search([])
                        for prod in all_products:
                            ratio = SequenceMatcher(None, base_name.lower(), prod.name.lower()).ratio() * 100
                            if ratio >= 90:  # Ana isim için yüksek benzerlik
                                if self._can_rebind_product_identity(prod, data):
                                    return prod, f'base_name_similar_{int(ratio)}%'

                # 5b. Normal benzerlik kontrolü
                all_products = ProductT.search([])
                for prod in all_products:
                    ratio = SequenceMatcher(None, name.lower(), prod.name.lower()).ratio() * 100
                    if ratio >= self.name_match_ratio:
                        if self._can_rebind_product_identity(prod, data):
                            return prod, f'name_similar_{int(ratio)}%'

        return None, None

    def _get_sku_prefix(self, sku):
        """SKU'nun ilk kelimesini (prefix) al"""
        if not sku:
            return ''
        return str(sku).strip().split()[0] if sku else ''

    def _extract_base_and_variant(self, name):
        """Ürün adından ana isim ve varyantı ayıkla

        Örnek: "BOLD SPEAKER (KIRMIZI)" → ("BOLD SPEAKER", "KIRMIZI")
        Örnek: "BOLD (AÇIK YEŞİL)" → ("BOLD", "AÇIK YEŞİL")
        """
        import re
        if not name:
            return name, None

        name = str(name).strip()

        # Parantez içeriğini bul
        match = re.match(r'^(.+?)\s*\(([^)]+)\)\s*$', name)
        if match:
            base_name = match.group(1).strip()
            variant = match.group(2).strip()
            return base_name, variant

        return name, None

    def _find_base_product_by_variant_group(self, variant_group):
        """xml_variant_group ile ana ürünü bul (paylaşılan grup anahtarıyla)"""
        if not variant_group:
            return None
        return self.env['product.template'].search([
            ('xml_variant_group', '=', variant_group),
        ], limit=1)

    def _find_base_product_by_sku_prefix(self, sku):
        """SKU'nun ortak ön ekini kullanarak ana ürünü bul.

        SKU formatları:
          'DT.VQEEM.027' veya 'DT-VQEEM-027' → 'DT.VQEEM' veya 'DT-VQEEM' (nokta/çizgi öncesi)
          'BDSPKRED' → 'BDSPK' (sayı öncesi)
        """
        if not sku:
            return None
        sku = str(sku).strip()

        # Ortak ön eki çıkar: nokta/çizgi/sayı ile biten kısmı at
        base_sku = re.sub(r'[.\-_][^.\-_]*$', '', sku)
        if not base_sku or base_sku == sku:
            base_sku = re.sub(r'\d+$', '', sku)
        if not base_sku or len(base_sku) < 3:
            return None

        templates = self.env['product.template'].search([
            ('default_code', '=like', base_sku + '%'),
        ])
        for tmpl in templates:
            if tmpl.product_variant_count > 0:
                return tmpl
        return None

    def _find_or_create_base_product(self, base_name, data, cost_price):
        """Ana ürünü bul veya oluştur (varyant için)"""
        self.ensure_one()
        Product = self.env['product.template']

        # Önce xml_variant_group ile bul
        variant_group = data.get('variant_group')
        if variant_group:
            product = self._find_base_product_by_variant_group(variant_group)
            if product:
                return product

        # Önce mevcut ürünü ara
        # 1. Tam isim eşleşmesi
        product = Product.search([('name', '=ilike', base_name)], limit=1)
        if product:
            return product

        # 2. SKU ortak ön eki ile ara
        sku = str(data.get('sku', '')).strip() if data.get('sku') else ''
        base_sku, _ = self._extract_base_and_variant(sku)
        if base_sku:
            product = Product.search([('default_code', '=', base_sku)], limit=1)
            if product:
                return product
            product = self._find_base_product_by_sku_prefix(base_sku)
            if product:
                return product

        # Ürün bulunamadı, yeni oluştur
        sale_price = self._calculate_sale_price(cost_price)

        vals = {
            'name': base_name,
            'default_code': base_sku if base_sku else None,
            'description_sale': data.get('description'),
            'list_price': sale_price,
            'standard_price': cost_price or 0,
            'xml_source_id': self.id,
            'xml_supplier_price': cost_price,
            'xml_supplier_sku': data.get('sku'),
            'xml_last_sync': fields.Datetime.now(),
            'is_dropship': True,
        }
        vals.update(self._normalized_product_defaults(data))

        # Kategori (manuel eşleştirme + otomatik)
        category_result = self._apply_category_mapping(data.get('category'), data.get('extra1'))
        if category_result.get('categ_id'):
            vals['categ_id'] = category_result['categ_id']
        if category_result.get('public_categ_ids'):
            vals['public_categ_ids'] = category_result['public_categ_ids']
        if not vals.get('categ_id'):
            default_category = self._default_category_for_usage(vals.get('xml_usage_class'))
            if default_category:
                vals['categ_id'] = default_category.id

        # Tedarikçi
        if self.supplier_id:
            vals['xml_supplier_id'] = self.supplier_id.id

        product = Product.create(vals)
        _logger.info(f"Ana ürün oluşturuldu: {base_name}")

        return product

    def _get_variant_attribute_from_mapping(self, variant_name, attribute=None, xml_attribute_name=None):
        """Varyant eşleştirme tablosundan attribute değerini bul

        Varsa mapping'deki attribute/value kullanılır,
        yoksa varsayılan davranışa dönülür.

        Args:
            variant_name: XML'den gelen varyant değeri
            attribute: İstenen attribute (varsa buna ait mapping'e bakar)
            xml_attribute_name: İç içe yapılarda özellik adı (opsiyonel)

        Returns:
            (attribute, attr_value) tuple veya (None, None)
        """
        mapping = self.env['xml.variant.mapping'].find_mapping(
            self.id, variant_name, xml_attribute_name=xml_attribute_name
        )
        if mapping:
            if attribute and mapping.attribute_id != attribute:
                return None, None
            return mapping.attribute_id, mapping.attribute_value_id
        return None, None

    def _apply_variant_attrs_to_template(self, product_tmpl, data):
        """_variant_attrs'teki attribute değerlerini ürüne uygula

        Her attribute için:
        1. xml.variant.mapping'den Odoo attribute value'yu bul
        2. Ürüne attribute line olarak ekle

        Returns:
            True varsa en az bir attribute eklendi, yoksa False
        """
        variant_attrs = data.get('_variant_attrs')
        _logger.info("DEBUG _apply_variant_attrs_to_template: _variant_attrs=%s", variant_attrs)
        if not variant_attrs:
            return False

        applied = False
        for attr_id_str, attr_info in variant_attrs.items():
            if not attr_info.get('resolved', True):
                continue
            attribute = attr_info['attribute']
            attr_names = attr_info.get('xml_attribute_names', [])
            for idx, xml_value in enumerate(attr_info['values']):
                xml_attr_name = attr_names[idx] if idx < len(attr_names) else None
                _attr, attr_value = self._get_variant_attribute_from_mapping(
                    xml_value, attribute=attribute, xml_attribute_name=xml_attr_name
                )
                if not attr_value:
                    attr_value = self.env['product.attribute.value'].search([
                        ('attribute_id', '=', attribute.id),
                        ('name', '=', xml_value),
                    ], limit=1)

                if not attr_value:
                    domain = [
                        ('source_id', '=', self.id),
                        ('xml_variant_value', '=', xml_value),
                        ('allow_create_value', '=', True),
                    ]
                    if xml_attr_name:
                        domain += [('xml_attribute_name', '=', xml_attr_name)]
                    mapping = self.env['xml.variant.mapping'].search(domain, limit=1)
                    if mapping:
                        attr_value = self.env['product.attribute.value'].create({
                            'attribute_id': attribute.id,
                            'name': xml_value,
                        })

                if not attr_value:
                    # Son çare: otomatik oluştur (nested XML'den gelen değer)
                    attr_value = self.env['product.attribute.value'].create({
                        'attribute_id': attribute.id,
                        'name': xml_value,
                    })
                    _logger.info(
                        "Varyant değeri otomatik oluşturuldu: %s → %s",
                        attribute.name, xml_value,
                    )

                if attr_value:
                    # Attribute line ekle veya güncelle
                    attr_line = self.env['product.template.attribute.line'].search([
                        ('product_tmpl_id', '=', product_tmpl.id),
                        ('attribute_id', '=', attribute.id),
                    ], limit=1)

                    if attr_line:
                        if attr_value not in attr_line.value_ids:
                            attr_line.write({'value_ids': [(4, attr_value.id)]})
                    else:
                        self.env['product.template.attribute.line'].create({
                            'product_tmpl_id': product_tmpl.id,
                            'attribute_id': attribute.id,
                            'value_ids': [(6, 0, [attr_value.id])],
                        })
                    applied = True

        if applied:
            # create_variants açıkken yeni varyant kayıtları oluştur
            if self.create_variants and hasattr(product_tmpl, 'create_variant_ids'):
                product_tmpl.create_variant_ids()
            self.env.cr.flush()
            product_tmpl.invalidate_recordset()
        return applied

    def _find_variant_by_attrs(self, product_tmpl, data):
        """_variant_attrs'teki attribute değerlerine uyan varyantı bul

        Returns:
            product.product record veya None
        """
        variant_attrs = data.get('_variant_attrs', {})
        if not variant_attrs:
            _logger.warning("DEBUG _find_variant_by_attrs: no _variant_attrs in data")
            return None

        target_attr_values = {}
        for attr_info in variant_attrs.values():
            if not attr_info.get('resolved', True):
                _logger.warning("DEBUG _find_variant_by_attrs: skipping unresolved attr_info: %s", attr_info)
                continue
            attribute = attr_info.get('attribute')
            if not attribute:
                _logger.warning("DEBUG _find_variant_by_attrs: attr_info has no attribute: %s", attr_info)
                continue
            for idx, xml_value in enumerate(attr_info['values']):
                xml_attr_names = attr_info.get('xml_attribute_names', [])
                xml_attr_name = xml_attr_names[idx] if idx < len(xml_attr_names) else None
                _attr, attr_value = self._get_variant_attribute_from_mapping(
                    xml_value, attribute=attribute, xml_attribute_name=xml_attr_name
                )
                if not attr_value:
                    attr_value = self.env['product.attribute.value'].search([
                        ('attribute_id', '=', attribute.id),
                        ('name', '=', xml_value),
                    ], limit=1)
                if attr_value:
                    target_attr_values.setdefault(attribute.id, set()).add(attr_value.id)
                else:
                    _logger.warning("DEBUG _find_variant_by_attrs: could not find value for attr=%s xml_value=%s",
                                    attribute.name, xml_value)

        if not target_attr_values:
            _logger.warning("DEBUG _find_variant_by_attrs: no target_attr_values built from variant_attrs")
            return None

        _logger.info("DEBUG _find_variant_by_attrs: target_attr_values=%s, total_variants=%s",
                     {attr_id: list(vals) for attr_id, vals in target_attr_values.items()},
                     len(product_tmpl.product_variant_ids))

        for variant in product_tmpl.product_variant_ids:
            variant_ptavs = variant.product_template_attribute_value_ids
            variant_attr_values = {}
            for ptav in variant_ptavs:
                attr_id = ptav.attribute_id.id
                val_id = ptav.product_attribute_value_id.id
                variant_attr_values.setdefault(attr_id, set()).add(val_id)

            _logger.info("DEBUG _find_variant_by_attrs: checking variant id=%s attrs=%s",
                         variant.id, {attr_id: list(vals) for attr_id, vals in variant_attr_values.items()})
            if variant_attr_values == target_attr_values:
                return variant

        _logger.warning("DEBUG _find_variant_by_attrs: no matching variant found")
        return None

    def _create_color_variant(self, product_tmpl, variant_name, data, cost_price):
        """Varyant oluştur (öncelik: field mapping, sonra variant eşleştirme, en son eski heuristics)"""
        self.ensure_one()

        variant_group = data.get('variant_group')
        if variant_group and not product_tmpl.xml_variant_group:
            product_tmpl.write({'xml_variant_group': variant_group})

        # 1) Field mapping'den _variant_attrs
        if self._apply_variant_attrs_to_template(product_tmpl, data):
            product_tmpl.invalidate_recordset()
            matching_variant = self._find_variant_by_attrs(product_tmpl, data)
            if matching_variant:
                variant_vals = {}
                barcode = data.get('barcode')
                if barcode:
                    variant_vals['barcode'] = barcode
                sku = data.get('sku')
                if sku:
                    variant_vals['default_code'] = sku
                if variant_vals:
                    matching_variant.write(variant_vals)
                _logger.info(f"Varyant (attr): {product_tmpl.name} - {variant_name}")
                return matching_variant
            # Fallback: ilk varyantı dene (tek attribute durumunda)
            for variant in product_tmpl.product_variant_ids:
                variant_vals = {}
                barcode = data.get('barcode')
                if barcode:
                    variant_vals['barcode'] = barcode
                sku = data.get('sku')
                if sku:
                    variant_vals['default_code'] = sku
                if variant_vals:
                    variant.write(variant_vals)
                _logger.info(f"Varyant (attr fallback): {product_tmpl.name} - {variant_name}")
                return variant

        # 2) Variant eşleştirme tablosundan bak
        attribute, attr_value = self._get_variant_attribute_from_mapping(variant_name)

        if not attribute or not attr_value:
            # 3) Eski yöntem: variant_attribute_name ile attribute/value bul/oluştur
            attr_name = self.variant_attribute_name or 'Renk'
            attribute = self.env['product.attribute'].search([
                ('name', '=', attr_name),
            ], limit=1)
            if not attribute:
                attribute = self.env['product.attribute'].create({
                    'name': attr_name,
                    'display_type': 'radio',
                    'create_variant': 'always',
                })
            attr_value = self.env['product.attribute.value'].search([
                ('attribute_id', '=', attribute.id),
                ('name', '=', variant_name),
            ], limit=1)
            if not attr_value:
                attr_value = self.env['product.attribute.value'].create({
                    'attribute_id': attribute.id,
                    'name': variant_name,
                })

        # Attribute line ekle/güncelle
        attr_line = self.env['product.template.attribute.line'].search([
            ('product_tmpl_id', '=', product_tmpl.id),
            ('attribute_id', '=', attribute.id),
        ], limit=1)
        if attr_line:
            if attr_value not in attr_line.value_ids:
                attr_line.write({'value_ids': [(4, attr_value.id)]})
        else:
            self.env['product.template.attribute.line'].create({
                'product_tmpl_id': product_tmpl.id,
                'attribute_id': attribute.id,
                'value_ids': [(6, 0, [attr_value.id])],
            })

        # Oluşan varyantı bul ve barkod ekle
        product_tmpl.invalidate_recordset()
        for variant in product_tmpl.product_variant_ids:
            if attr_value in variant.product_template_attribute_value_ids.mapped('product_attribute_value_id'):
                barcode = data.get('barcode')
                if barcode:
                    variant.write({'barcode': barcode})
                _logger.info(f"Varyant: {product_tmpl.name} - {variant_name} -> {attr_value.name}")
                return variant

        return None

    # ══════════════════════════════════════════════════════════════════════════
    # IMPORT LOGIC
    # ══════════════════════════════════════════════════════════════════════════

    def action_test_connection(self):
        """Bağlantıyı test et"""
        self.ensure_one()

        try:
            xml_content = self._fetch_xml()
            products = self._parse_xml(xml_content)

            self.write({
                'state': 'active',
                'last_error': False,
            })

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Bağlantı Başarılı'),
                    'message': _('XML\'de %s ürün bulundu.') % len(products),
                    'type': 'success',
                    'sticky': False,
                }
            }

        except Exception as e:
            self.write({
                'state': 'error',
                'last_error': str(e),
            })
            raise UserError(_('Bağlantı hatası: %s') % str(e))

    def _xml_structure_preview(self, element, max_depth=3):
        """XML element yapısını göster - derinlik aşıldığında çocuk tagları ve değerleri göster"""
        lines = []
        tag = element.tag.split('}')[-1]
        children = list(element)
        attrs = dict(element.attrib)
        text = (element.text or '').strip()[:60]

        if not children and not attrs:
            if text:
                lines.append(f"<{tag}>{text}...</{tag}>")
            else:
                lines.append(f"<{tag}/>")
        else:
            attr_str = ''
            if attrs:
                attr_str = ' ' + ' '.join(f'{k}="{v}"' for k, v in attrs.items())
            lines.append(f"<{tag}{attr_str}>")
            if text:
                lines.append(f"  {text}...")
            if max_depth > 0:
                for child in children:
                    for cl in self._xml_structure_preview(child, max_depth - 1):
                        lines.append(f"  {cl}")
            elif children:
                child_parts = []
                for child in children[:5]:
                    c_tag = child.tag.split('}')[-1]
                    c_children = list(child)
                    c_text = (child.text or '').strip()[:20]
                    if not c_children and c_text:
                        child_parts.append(f"<{c_tag}>{c_text}...</{c_tag}>")
                    elif c_children:
                        gc_parts = []
                        for gc in c_children[:3]:
                            gc_tag = gc.tag.split('}')[-1]
                            gc_text = (gc.text or '').strip()[:20]
                            if gc_text:
                                gc_parts.append(f"<{gc_tag}>{gc_text}...</{gc_tag}>")
                            else:
                                gc_parts.append(f"<{gc_tag}/>")
                        rest = len(c_children) - 3
                        if rest > 0:
                            gc_parts.append(f"...+{rest}")
                        child_parts.append(f"<{c_tag}> {' '.join(gc_parts)} </{c_tag}>")
                    else:
                        child_parts.append(f"<{c_tag}/>")
                rest = len(children) - 5
                if rest > 0:
                    child_parts.append(f"...+{rest}")
                lines.append(f"  {' '.join(child_parts)}")
            lines.append(f"</{tag}>")
        return lines

    def _build_structured_preview(self, elements, has_variant_mappings, flat_products):
        """Sol tab: yapı + kısaltılmış veri (ilk 5 ürün)"""
        lines = []
        lines.append(f"Toplam {len(elements)} ürün bulundu")
        if has_variant_mappings:
            vc = sum(1 for _, ve, _ in flat_products if ve is not None)
            nv = sum(1 for _, ve, _ in flat_products if ve is None)
            lines.append(f"{nv} normal + {vc} varyant")
        lines.append("")

        lines.append("── XML YAPISI (ilk 5 ürün) ──")
        for pi in range(min(5, len(elements))):
            lines.append("")
            lines.append(f"  Ürün {pi+1}:")
            for line in self._xml_structure_preview(elements[pi]):
                lines.append(f"    {line}")
        lines.append("")
        lines.append("── ÜRÜN VERİLERİ (ilk 5) ──")
        lines.append("")

        for i, element in enumerate(elements[:5]):
            data = self._extract_product_data(element, strict=True)
            if has_variant_mappings:
                el_variants = [(ve, mc) for e, ve, mc in flat_products if id(e) == id(element)]
                sub_variants = [ve for ve, _ in el_variants if ve is not None]
                if sub_variants:
                    self._apply_variant_overrides(data, sub_variants[0], el_variants[0][1])
            else:
                sub_variants = []

            preview_data = {k: v for k, v in data.items() if k != '_variant_attrs'}
            # Değerleri kısalt
            for k, v in preview_data.items():
                if isinstance(v, str) and len(v) > 60:
                    preview_data[k] = v[:60] + '...'

            lines.append(f"Ürün {i+1}: {json.dumps(preview_data, ensure_ascii=False, indent=2, default=str)}")
            if sub_variants:
                lines.append(f"  └ Varyantlar ({len(sub_variants)} adet)")
            lines.append("")

        remaining = len(elements) - 5
        if remaining > 0:
            lines.append(f"... ve {remaining} ürün daha (toplam {len(elements)})")
        return '\n'.join(lines)

    def _build_raw_preview(self, elements, has_variant_mappings, flat_products):
        """Sağ tab: orijinal extract çıktısı (ilk 5 ürün)"""
        lines = []
        lines.append(f"Toplam {len(elements)} ürün")
        if has_variant_mappings:
            vc = sum(1 for _, ve, _ in flat_products if ve is not None)
            nv = sum(1 for _, ve, _ in flat_products if ve is None)
            lines.append(f"{nv} normal + {vc} varyant")
        lines.append("")

        for i, element in enumerate(elements[:5]):
            data = self._extract_product_data(element, strict=True)
            if has_variant_mappings:
                el_variants = [(ve, mc) for e, ve, mc in flat_products if id(e) == id(element)]
                sub_variants = [ve for ve, _ in el_variants if ve is not None]
                if sub_variants:
                    self._apply_variant_overrides(data, sub_variants[0], el_variants[0][1])

            raw_data = {k: v for k, v in data.items() if k != '_variant_attrs'}
            lines.append(f"Ürün {i+1}: {json.dumps(raw_data, ensure_ascii=False, indent=2, default=str)}")

            if has_variant_mappings:
                el_variants = [(ve, mc) for e, ve, mc in flat_products if id(e) == id(element)]
                sub_variants = [ve for ve, _ in el_variants if ve is not None]
                if sub_variants:
                    lines.append(f"  └ Varyantlar ({len(sub_variants)} adet):")
                    for vi, ve in enumerate(sub_variants[:5]):
                        vb = (ve.findtext('Barcode') or '').strip()
                        vk = (ve.findtext('VariantCode') or '').strip()
                        vs = (ve.findtext('Stock') or '').strip()
                        vp = (ve.findtext('Price') or '').strip()
                        lines.append(f"     {vi+1}. Kod={vk} Barkod={vb} Stok={vs} Fiyat={vp}")
            lines.append("")

        remaining = len(elements) - 5
        if remaining > 0:
            lines.append(f"... ve {remaining} ürün daha")
        return '\n'.join(lines)

    def _build_paths_preview(self, elements):
        """Tüm XML yollarını örnek değerlerle listele (ilk 3 ürün)"""
        from collections import OrderedDict

        def walk(element, prefix=''):
            paths = OrderedDict()
            tag = element.tag.split('}')[-1]
            current = f"{prefix}/{tag}" if prefix else tag

            for attr_name, attr_value in (element.attrib or {}).items():
                paths[f"{current}/@{attr_name}"] = attr_value

            text = (element.text or '').strip()
            children = list(element)
            if not children and text:
                if current not in paths:
                    paths[current] = text

            for child in children:
                child_paths = walk(child, current)
                for k, v in child_paths.items():
                    if k not in paths:
                        paths[k] = v
            return paths

        all_paths = OrderedDict()
        for pi in range(min(3, len(elements))):
            el = elements[pi]
            # Ürün elementinin attribute'ları (@id, @code vb.)
            for attr_name, attr_value in (el.attrib or {}).items():
                path = f"@{attr_name}"
                if path not in all_paths:
                    all_paths[path] = attr_value
            # Çocuk elementlerden yolları çıkar (product tag'ini atla)
            for child in list(el):
                child_paths = walk(child)
                for k, v in child_paths.items():
                    if k not in all_paths:
                        all_paths[k] = v

        lines = []
        lines.append(f"Toplam {len(all_paths)} yol bulundu (ilk 3 üründen)")
        lines.append("")
        lines.append("  YOL                                   │ ÖRNEK DEĞER")
        lines.append("  ───────────────────────────────────────┼──────────────────────────────")
        for path, value in all_paths.items():
            val = (value or '').strip()[:60]
            lines.append(f"  {path:<40} │ {val}")
        lines.append("")
        lines.append("── KULLANIM ──")
        lines.append("  Bu yolları Alan Eşleştirmesi > XML Yolu alanına yazabilirsiniz.")
        lines.append("  Örn: ProductCode  ->  Ürün Kodu için")
        lines.append("  Örn: Category/Name  ->  Kategori için")
        lines.append("  Örn: Images/Image/Url  ->  Görsel için")
        return '\n'.join(lines)

    def action_preview_xml(self):
        """XML içeriğini önizle"""
        self.ensure_one()

        try:
            xml_content = self._fetch_xml()
            elements = self._parse_xml(xml_content)

            if not elements:
                raise UserError(_('XML\'de ürün bulunamadı. Root element yolunu kontrol edin.'))

            has_variant_mappings = any(
                m.odoo_field == 'variant_attribute' for m in self.field_mapping_ids
            )
            if has_variant_mappings:
                flat_products = self._expand_nested_variants(elements)
            else:
                flat_products = []

            wizard = self.env['xml.preview.wizard'].create({
                'structured_view': self._build_structured_preview(elements, has_variant_mappings, flat_products),
                'raw_view': self._build_raw_preview(elements, has_variant_mappings, flat_products),
                'paths_view': self._build_paths_preview(elements),
            })

            return {
                'type': 'ir.actions.act_window',
                'res_model': 'xml.preview.wizard',
                'view_mode': 'form',
                'view_id': self.env.ref('mobilsoft_xml_import.xml_preview_wizard_form_view').id,
                'target': 'new',
                'res_id': wizard.id,
            }

        except Exception as e:
            raise UserError(_('Önizleme hatası: %s') % str(e))

    def action_discover_xml_paths(self):
        """XML'deki tüm yolları tespit et ve xml.source.path kayıtlarını oluştur"""
        self.ensure_one()
        count = self.env['xml.source.path'].discover_from_source(self)
        if count:
            msg = _('%d XML yolu tespit edildi. Alan Eşleştirmesi > XML Yolu (Seç) alanından seçebilirsiniz.') % len(count)
        else:
            msg = _('XML yolu tespit edilemedi. XML içeriğini kontrol edin.')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Yollar Tespit Edildi'),
                'message': msg,
                'sticky': False,
                'type': 'success' if count else 'warning',
            },
        }

    def action_import_products(self):
        """Ürünleri içe aktar"""
        self.ensure_one()
        _logger.warning("action_import_products called for source ID: %s - %s (self len: %s)", self.id, self.name, len(self))

        # Log oluştur
        log = self.env['xml.import.log'].create({
            'source_id': self.id,
            'start_time': fields.Datetime.now(),
            'state': 'running',
        })

        created = updated = skipped = failed = 0
        processed_since_commit = 0
        errors = []

        try:
            # XML çek ve parse et
            xml_content = self._fetch_xml()
            elements = self._parse_xml(xml_content)

            # <Variants>/<Variant> içeren ürünleri düzleştir
            flat_products = self._expand_nested_variants(elements)

            # Index Grup / Netex: Ayrı stok ve fiyat feedlerini önceden çek
            _ig_stock_map = {}
            _ig_price_map = {}
            if self.xml_template in ('indexgrup', 'netex'):
                _ig_stock_map = self._fetch_indexgrup_stock_map()
                _ig_price_map = self._fetch_indexgrup_price_map()

            log.total_products = len(flat_products)

            _logger.info(f"XML Import: {len(flat_products)} ürün/varyant bulundu - {self.name}")

            for element, v_elem, main_code in flat_products:
                try:
                    # Ürün bazında SQL hataları transaction'ı abort etmesin diye savepoint kullan.
                    # (Aksi halde bir ürün hatasından sonra self.write/log.write InFailedSqlTransaction'a düşer.)
                    with self.env.cr.savepoint():
                        # Ürün verilerini çıkar
                        data = self._extract_product_data(element)

                        # Nested <Variants>/<Variant> override
                        if v_elem is not None:
                            self._apply_variant_overrides(data, v_elem, main_code)

                        # Index Grup / Netex: Stok ve fiyat bilgilerini birleştir
                        if self.xml_template in ('indexgrup', 'netex'):
                            globalkod = data.get('sku', '')
                            if globalkod and globalkod in _ig_stock_map:
                                data['stock'] = str(_ig_stock_map[globalkod])
                            if globalkod and globalkod in _ig_price_map:
                                pinfo = _ig_price_map[globalkod]
                                data['cost_price'] = str(pinfo.get('cost_price', 0))
                                data['price'] = str(pinfo.get('dealer_price', 0) or pinfo.get('cost_price', 0))
                                if pinfo.get('currency'):
                                    data['currency'] = pinfo['currency']

                        if not data.get('name'):
                            skipped += 1
                            continue

                        skip_product, skip_reason = self._should_skip_product_data(data)
                        if skip_product:
                            skipped += 1
                            _logger.info('XML import skip: %s - %s', data.get('name'), skip_reason)
                            continue

                        # Fiyat kontrolü
                        price = float(data.get('price', 0) or 0)
                        cost = float(data.get('cost_price', 0) or data.get('price', 0) or 0)

                        if self.min_price and price < self.min_price:
                            skipped += 1
                            continue
                        if self.max_price and price > self.max_price:
                            skipped += 1
                            continue

                        # Stok kontrolü (sadece min_stock > 0 ise kontrol et)
                        stock = int(data.get('stock', 0) or 0)
                        if self.min_stock > 0 and stock < self.min_stock:
                            # Stok min_stock altında - mevcut ürünü kontrol et
                            existing, match_type = self._find_existing_product(data)
                            if existing and existing.exists():
                                # Tedarikçi stoğunu güncelle
                                existing.write({
                                    'xml_supplier_stock': stock,
                                    'xml_last_sync': fields.Datetime.now(),
                                })
                                # Stok 0 ise ve ayarlar aktifse işle
                                if stock == 0 and (self.deactivate_zero_stock or self.delete_unsold_zero_stock):
                                    self._handle_zero_stock_product(existing)
                                elif self.deactivate_zero_stock and existing.exists():
                                    # Stok min_stock altında ama 0 değil - sadece satışa kapat
                                    existing.write({'sale_ok': False})
                                    _logger.info(f"Stok yetersiz ({stock} < {self.min_stock}) - ürün satışa kapatıldı: {existing.name}")
                            skipped += 1
                            continue

                        # Mevcut ürün ara
                        existing, match_type = self._find_existing_product(data)
                        usage_class = self._classify_usage(data)

                        # Parantezden varyant kontrolü
                        name = str(data.get('name', '')).strip()
                        base_name, variant_name = self._extract_base_and_variant(name)

                        if existing:
                            # Arşivlenmiş ürün eşleştiyse aktif hale getir (tekilleştirme için)
                            if hasattr(existing, 'active') and not existing.active:
                                reactivate_vals = {'active': True, 'purchase_ok': True}
                                if usage_class == 'commercial':
                                    reactivate_vals['sale_ok'] = True
                                existing.write(reactivate_vals)
                                # Şablon aktif olurken varyantları da aktif et (aksi halde barkod eşleşmesi zorlaşır)
                                variants = existing.with_context(active_test=False).product_variant_ids
                                if variants:
                                    variants.write({'active': True})

                            # Varyant kararı: 1) _variant_attrs (field mapping) 2) parantez 3) variant_group 4) SKU prefix
                            should_create_variant = False
                            variant_identifier = None

                            if usage_class == 'commercial':
                                if data.get('_variant_attrs'):
                                    # Field mapping'den gelen varyant - her zaman işle
                                    # (create_variants kapalı olsa bile mevcut varyantı güncelle)
                                    should_create_variant = True
                                    variant_identifier = name
                                elif self.create_variants and self.variant_from_parentheses and variant_name:
                                    should_create_variant = True
                                    variant_identifier = variant_name
                                elif self.create_variants and data.get('variant_group'):
                                    base_by_group = self._find_base_product_by_variant_group(data['variant_group'])
                                    if base_by_group and base_by_group != existing:
                                        existing = base_by_group
                                        should_create_variant = True
                                        variant_identifier = name
                                elif self.create_variants and data.get('barcode'):
                                    item_sku = str(data.get('sku', '')).strip()
                                    base_by_sku = self._find_base_product_by_sku_prefix(item_sku) if item_sku else None
                                    if base_by_sku and base_by_sku != existing:
                                        existing = base_by_sku
                                        should_create_variant = True
                                        variant_identifier = name

                            if should_create_variant and variant_identifier:
                                # Bu varyant zaten var mı kontrol et (barkod ile)
                                barcode = data.get('barcode')
                                existing_variant = self.env['product.product'].with_context(active_test=False).search([
                                    ('barcode', '=', barcode)
                                ], limit=1) if barcode else None

                                if not existing_variant:
                                    # Yeni varyant ekle
                                    self._create_color_variant(existing, variant_identifier, data, cost)
                                    updated += 1
                                    _logger.info(f"Varyant eklendi: {existing.name} - {variant_identifier}")
                                elif self.update_existing:
                                    # Varyant zaten var, güncelle
                                    self._update_product(existing, data, cost, price)
                                    updated += 1
                                else:
                                    skipped += 1
                            elif self.update_existing:
                                self._update_product(existing, data, cost, price)
                                updated += 1
                            else:
                                skipped += 1
                        else:
                            if self.create_new_products:
                                self._create_product(data, cost, price)
                                created += 1
                            else:
                                skipped += 1

                except Exception as e:
                    failed += 1
                    errors.append(f"{data.get('name', 'Bilinmiyor')}: {str(e)}")
                    _logger.error(f"Ürün import hatası: {e}")

                processed_since_commit += 1
                if processed_since_commit >= 50:
                    self.env.cr.commit()
                    processed_since_commit = 0

            # Sonuçları kaydet
            if processed_since_commit:
                self.env.cr.commit()
            self.write({
                'last_sync': fields.Datetime.now(),
                'state': 'active',
                'last_error': False,
            })

            log.write({
                'end_time': fields.Datetime.now(),
                'state': 'done',
                'products_created': created,
                'products_updated': updated,
                'products_skipped': skipped,
                'products_failed': failed,
                'error_details': '\n'.join(errors) if errors else False,
            })

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('İçe Aktarım Tamamlandı'),
                    'message': _('Oluşturulan: %s, Güncellenen: %s, Atlanan: %s, Hatalı: %s') % (
                        created, updated, skipped, failed
                    ),
                    'type': 'success' if failed == 0 else 'warning',
                    'sticky': True,
                }
            }

        except Exception as e:
            self.write({
                'state': 'error',
                'last_error': str(e),
            })
            log.write({
                'end_time': fields.Datetime.now(),
                'state': 'error',
                'error_details': str(e),
            })
            raise UserError(_('İçe aktarım hatası: %s') % str(e))

    def _create_product(self, data, cost_price, xml_price):
        """Yeni ürün oluştur veya varyant ekle"""
        self.ensure_one()

        name = str(data.get('name', '')).strip() if data.get('name') else ''
        sku = str(data.get('sku', '')).strip() if data.get('sku') else ''

        # ═══════════════════════════════════════════════════════════════
        # PARANTEZDEN VARYANT MODU
        # Örnek: "BOLD SPEAKER (KIRMIZI)" → Ana ürün: BOLD SPEAKER, Varyant: KIRMIZI
        # ═══════════════════════════════════════════════════════════════
        usage_class = self._classify_usage(data)

        if usage_class == 'commercial' and self.variant_from_parentheses and self.create_variants:
            base_name, variant_name = self._extract_base_and_variant(name)

            if variant_name:
                # Parantez içinde varyant bilgisi var
                # Aynı barkod zaten var mı kontrol et
                existing_barcode = self.env['product.product'].search([
                    ('barcode', '=', data.get('barcode')),
                ], limit=1)

                if existing_barcode:
                    # Bu barkod zaten var, güncelle
                    _logger.debug(f"Barkod zaten mevcut, güncelleme yapılacak: {data.get('barcode')}")
                    return existing_barcode.product_tmpl_id

                # Ana ürünü bul veya oluştur
                base_product = self._find_or_create_base_product(base_name, data, cost_price)

                # Varyant oluştur
                variant = self._create_color_variant(base_product, variant_name, data, cost_price)
                if variant:
                    return base_product

        # ═══════════════════════════════════════════════════════════════
        # STANDART VARYANT MODU (SKU prefix / variant_group tabanlı)
        # ═══════════════════════════════════════════════════════════════
        variant_group = data.get('variant_group')

        # _variant_attrs field mapping'den geldiyse standard barcode varyant modunu atla
        if usage_class == 'commercial' and self.create_variants and data.get('barcode') and not data.get('_variant_attrs'):
            base_by_variant_group = self._find_base_product_by_variant_group(variant_group) if variant_group else None
            base_by_sku_prefix = self._find_base_product_by_sku_prefix(sku) if sku else None

            existing_base = base_by_variant_group or base_by_sku_prefix

            if existing_base:
                existing_barcode = self.env['product.product'].search([
                    ('barcode', '=', data.get('barcode')),
                ], limit=1)

                if not existing_barcode:
                    return self._create_variant(existing_base, data, cost_price)

        # Barkod ve SKU yoksa isimle son bir duplikat kontrolü yap
        if not data.get('barcode') and not sku:
            name_check = str(data.get('name', '')).strip()
            if name_check:
                existing_by_name = self.env['product.template'].search(
                    [('name', '=ilike', name_check)], limit=1
                )
                if existing_by_name:
                    _logger.info(f"İsim eşleşmesiyle duplikat engellendi: {name_check} → ID {existing_by_name.id}")
                    return existing_by_name

        sale_price = self._calculate_sale_price(cost_price)

        vals = {
            'name': data.get('name'),
            'default_code': data.get('sku'),
            'barcode': data.get('barcode'),
            'description_sale': data.get('description'),
            'list_price': sale_price,
            'standard_price': cost_price,
            # Dropshipping alanları
            'xml_source_id': self.id,
            'xml_supplier_price': cost_price,
            'xml_supplier_sku': data.get('sku'),
            'xml_last_sync': fields.Datetime.now(),
            'is_dropship': True,
        }
        vals.update(self._normalized_product_defaults(data))

        # Görsel
        if data.get('image'):
            image_url = data.get('image')
            vals['xml_image_url'] = image_url
            # Görseli indir veya URL olarak ekle
            if self.download_images:
                image_data = self._download_image(image_url)
                if image_data:
                    vals['image_1920'] = image_data

        # Açıklama
        if data.get('description'):
            description = data.get('description')
            # HTML temizleme (opsiyonel)
            description = self._clean_html(description)
            vals['description_sale'] = description
            vals['description'] = description

        # Kısa açıklama → teslim notu alanı
        if data.get('description_short'):
            vals['description_picking'] = self._clean_html(data['description_short'])

        # Tedarikçi stok
        if data.get('stock'):
            try:
                vals['xml_supplier_stock'] = int(data.get('stock'))
            except (ValueError, TypeError):
                pass

        # Kategori eşleştirme (manuel + otomatik)
        category_result = self._apply_category_mapping(data.get('category'), data.get('extra1'))
        if category_result.get('categ_id'):
            vals['categ_id'] = category_result['categ_id']
        if category_result.get('public_categ_ids'):
            vals['public_categ_ids'] = category_result['public_categ_ids']
        if not vals.get('categ_id'):
            default_category = self._default_category_for_usage(vals.get('xml_usage_class'))
            if default_category:
                vals['categ_id'] = default_category.id

        if self.supplier_id:
            vals['xml_supplier_id'] = self.supplier_id.id

        # Desi/Ağırlık
        if data.get('weight'):
            try:
                vals['weight'] = float(data['weight'])
            except (ValueError, TypeError):
                pass

        if data.get('deci'):
            try:
                vals['volume'] = float(data['deci'])
                vals['deci'] = float(data['deci'])
            except (ValueError, TypeError):
                pass

        # Marka
        if data.get('brand'):
            vals['xml_brand'] = str(data['brand']).strip()

        # Garanti
        if data.get('warranty'):
            vals['xml_warranty'] = str(data['warranty']).strip()

        # Model
        if data.get('model'):
            vals['xml_model'] = str(data['model']).strip()

        # Menşei
        if data.get('origin'):
            vals['xml_origin'] = str(data['origin']).strip()

        # Ekstra alanlar
        if data.get('extra2'):
            vals['xml_extra2'] = str(data['extra2']).strip()
        if data.get('extra3'):
            vals['xml_extra3'] = str(data['extra3']).strip()

        # KDV (taxes_id)
        if data.get('tax'):
            tax = self._find_tax_by_value(data['tax'])
            if tax:
                vals['taxes_id'] = [(6, 0, [tax.id])]

        product = self.env['product.template'].create(vals)

        # Varyant attribute'larını uygula (field mapping'den geliyorsa)
        # create_variants kapalı olsa bile attribute line'ları ekle (mevcut varyant eşleşmesi için)
        if data.get('_variant_attrs'):
            self._apply_variant_attrs_to_template(product, data)
            product.invalidate_recordset()
            matching_variant = self._find_variant_by_attrs(product, data)
            if matching_variant and data.get('barcode'):
                matching_variant.write({'barcode': data['barcode']})

        # Görsel URL olarak ekle (indirmeden)
        if data.get('image') and not self.download_images:
            self._set_image_from_url(product, data.get('image'))

        # Ek görseller ekle
        if data.get('extra_images'):
            if self.download_images:
                self._add_extra_images(product, data.get('extra_images'))
            else:
                self._add_extra_images_from_url(product, data.get('extra_images'))

        # Dropship rotası ekle (stock_dropshipping modülü)
        dropship_route = self.env.ref('stock_dropshipping.route_drop_shipping', raise_if_not_found=False)
        if dropship_route:
            product.write({'route_ids': [(4, dropship_route.id)]})

        # Tedarikçi fiyat/kod product.supplierinfo ile senkron (product_template inverse ile yazılıyor)

        _logger.info(f"Yeni ürün oluşturuldu (Dropship): {product.name}")

        return product

    def _add_extra_images(self, product, image_urls):
        """Ürüne ek görseller ekle"""
        if not image_urls:
            return

        ProductImage = self.env.get('product.image')
        if not ProductImage:
            # product.image modeli yoksa URL'leri text alanında sakla
            urls_text = '\n'.join(image_urls)
            product.write({'xml_image_urls': urls_text})
            return

        for i, url in enumerate(image_urls[:5]):  # Max 5 ek görsel
            try:
                image_data = self._download_image(url)
                if image_data:
                    ProductImage.create({
                        'product_tmpl_id': product.id,
                        'name': f"{product.name} - Görsel {i+2}",
                        'image_1920': image_data,
                    })
                    _logger.debug(f"Ek görsel eklendi: {product.name} - {i+2}")
            except Exception as e:
                _logger.warning(f"Ek görsel eklenemedi: {url} - {e}")

    def _set_image_from_url(self, product, image_url):
        """
        Ürüne görsel URL'sini kaydet.

        Not: Bu akış "download_images=False" iken kullanılır. Bu durumda görsel indirmek
        ürün güncellemesini çok yavaşlatabildiği için sadece URL saklanır.
        """
        if not image_url:
            return

        # URL'yi kaydet
        product.write({'xml_image_url': image_url})


    def _add_extra_images_from_url(self, product, image_urls):
        """Ürüne ek görsel URL'lerini ekle (indirmeden, sadece URL saklanır)"""
        if not image_urls:
            return

        # URL'leri text alanında sakla - disk tasarrufu
        urls_text = '\n'.join(image_urls[:10])  # Max 10 ek görsel URL
        product.write({'xml_image_urls': urls_text})
        _logger.debug(f"Ek görsel URL'leri kaydedildi: {product.name} - {len(image_urls)} adet")

    def _create_variant(self, product_tmpl, data, cost_price):
        """Mevcut ürüne varyant ekle (farklı barkod)"""
        self.ensure_one()

        # xml_variant_group kaydet (sonraki import'larda bulunsun diye)
        variant_group = data.get('variant_group')
        if variant_group and not product_tmpl.xml_variant_group:
            product_tmpl.write({'xml_variant_group': variant_group})

        # Barkod attribute'u bul veya oluştur
        barcode_attr = self.env['product.attribute'].search([
            ('name', '=', 'Barkod'),
        ], limit=1)

        if not barcode_attr:
            barcode_attr = self.env['product.attribute'].create({
                'name': 'Barkod',
                'display_type': 'radio',
                'create_variant': 'always',
            })

        barcode_value = data.get('barcode')

        # Attribute value bul veya oluştur
        attr_value = self.env['product.attribute.value'].search([
            ('attribute_id', '=', barcode_attr.id),
            ('name', '=', barcode_value),
        ], limit=1)

        if not attr_value:
            attr_value = self.env['product.attribute.value'].create({
                'attribute_id': barcode_attr.id,
                'name': barcode_value,
            })

        # Ürüne attribute line ekle
        attr_line = self.env['product.template.attribute.line'].search([
            ('product_tmpl_id', '=', product_tmpl.id),
            ('attribute_id', '=', barcode_attr.id),
        ], limit=1)

        if attr_line:
            # Mevcut line'a value ekle
            attr_line.write({'value_ids': [(4, attr_value.id)]})
        else:
            # Yeni attribute line oluştur
            self.env['product.template.attribute.line'].create({
                'product_tmpl_id': product_tmpl.id,
                'attribute_id': barcode_attr.id,
                'value_ids': [(6, 0, [attr_value.id])],
            })

        # Varyantları oluştur ve önbelleği temizle
        if hasattr(product_tmpl, 'create_variant_ids'):
            product_tmpl.create_variant_ids()
        self.env.cr.flush()
        product_tmpl.invalidate_recordset()

        # Yeni varyantı bul ve güncelle
        new_variant = self.env['product.product'].search([
            ('product_tmpl_id', '=', product_tmpl.id),
            ('barcode', '=', False),
        ], limit=1)

        if new_variant:
            new_variant.write({
                'barcode': barcode_value,
                'default_code': f"{data.get('sku')}-{barcode_value[-4:]}",
            })

        _logger.info(f"Varyant eklendi: {product_tmpl.name} - Barkod: {barcode_value}")

        return product_tmpl

    def _update_product(self, product, data, cost_price, xml_price):
        """Mevcut ürünü güncelle"""
        self.ensure_one()
        protect_core = self._is_reference_locked_product(product) or not self._can_rebind_product_identity(product, data)
        usage_class = self._classify_usage(data)

        vals = {
            'xml_source_id': self.id,
            'xml_supplier_sku': data.get('sku'),
            'xml_last_sync': fields.Datetime.now(),
            'is_dropship': True,
        }
        vals.update(self._normalized_product_defaults(data, protect_core=protect_core))

        # Muhasebeye bağlanmış ürünlerde ad/kod gibi çekirdek kimlikleri oynatma.
        if data.get('name') and not protect_core:
            vals['name'] = data['name']

        # İç referans (default_code) güncelleme
        if data.get('sku') and not protect_core:
            base_sku, _ = self._extract_base_and_variant(str(data['sku']).strip())
            if base_sku:
                vals['default_code'] = base_sku

        # Fiyat güncelleme - sadece değer varsa güncelle kuralına göre
        if self.update_price:
            if cost_price and cost_price > 0:
                sale_price = self._calculate_sale_price(cost_price)
                vals['list_price'] = sale_price
                vals['standard_price'] = cost_price
                vals['xml_supplier_price'] = cost_price
            elif not self.update_only_if_value:
                # update_only_if_value kapalıysa, değer olmasa da güncelle
                sale_price = self._calculate_sale_price(cost_price or 0)
                vals['list_price'] = sale_price
                vals['standard_price'] = cost_price or 0
                vals['xml_supplier_price'] = cost_price or 0
        elif cost_price and cost_price > 0:
            # Fiyat güncellemesi kapalı ama tedarikçi fiyatını kaydet
            vals['xml_supplier_price'] = cost_price

        # Stok güncelleme - sadece değer varsa güncelle kuralına göre
        if self.update_stock:
            stock_val = data.get('stock')
            if stock_val is not None and str(stock_val).strip():
                try:
                    stock_qty = int(stock_val)
                    vals['xml_supplier_stock'] = stock_qty
                    # Stok yeterli, daha önce kapatıldıysa tekrar aç
                    if usage_class == 'commercial' and stock_qty >= self.min_stock and not product.sale_ok:
                        vals['sale_ok'] = True
                        _logger.info(f"Stok yeterli ({stock_qty}) - ürün satışa tekrar açıldı: {product.name}")
                except (ValueError, TypeError):
                    pass
            elif not self.update_only_if_value:
                # update_only_if_value kapalıysa, değer olmasa da güncelle (0 yap)
                vals['xml_supplier_stock'] = 0

        # Görsel güncelle
        if self.update_images and data.get('image'):
            image_url = data.get('image')
            vals['xml_image_url'] = image_url
            # Görseli indir veya URL olarak ekle
            if self.download_images:
                image_data = self._download_image(image_url)
                if image_data:
                    vals['image_1920'] = image_data

        # Açıklama güncelle
        if self.update_description and data.get('description'):
            description = data.get('description')
            description = self._clean_html(description)
            vals['description_sale'] = description
            vals['description'] = description

        # Kategori güncelleme (manuel + otomatik)
        if data.get('category'):
            category_result = self._apply_category_mapping(data.get('category'), data.get('extra1'))
            if category_result.get('categ_id'):
                vals['categ_id'] = category_result['categ_id']
            if category_result.get('public_categ_ids'):
                vals['public_categ_ids'] = category_result['public_categ_ids']
        if not vals.get('categ_id'):
            default_category = self._default_category_for_usage(usage_class)
            if default_category:
                vals['categ_id'] = default_category.id

        if self.supplier_id:
            vals['xml_supplier_id'] = self.supplier_id.id

        # Marka
        if data.get('brand'):
            vals['xml_brand'] = str(data['brand']).strip()

        # Garanti
        if data.get('warranty'):
            vals['xml_warranty'] = str(data['warranty']).strip()

        # Model
        if data.get('model'):
            vals['xml_model'] = str(data['model']).strip()

        # Menşei
        if data.get('origin'):
            vals['xml_origin'] = str(data['origin']).strip()

        # Kısa açıklama → teslim notu alanı
        if data.get('description_short'):
            vals['description_picking'] = self._clean_html(data['description_short'])

        # Ekstra alanlar
        if data.get('extra2'):
            vals['xml_extra2'] = str(data['extra2']).strip()
        if data.get('extra3'):
            vals['xml_extra3'] = str(data['extra3']).strip()

        # KDV (taxes_id) — sadece mevcut yoksa ekle, üzerine yazma
        if data.get('tax') and not product.taxes_id:
            tax = self._find_tax_by_value(data['tax'])
            if tax:
                vals['taxes_id'] = [(6, 0, [tax.id])]

        product.write(vals)

        # Barkod güncelleme — product.product varyantı üzerinde
        if data.get('barcode'):
            barcode = str(data['barcode']).strip()
            if barcode:
                variants = product.product_variant_ids
                if len(variants) == 1:
                    # Tek varyanttaki barkodu güncelle (farklıysa)
                    if variants.barcode != barcode and self._can_rebind_product_identity(product, data):
                        variants.write({'barcode': barcode})

        # Görsel URL olarak ekle (güncelleme sonrası)
        if self.update_images and data.get('image') and not self.download_images:
            self._set_image_from_url(product, data.get('image'))

        # Ek görselleri güncelle
        if self.update_images and data.get('extra_images'):
            if self.download_images:
                self._add_extra_images(product, data.get('extra_images'))
            else:
                self._add_extra_images_from_url(product, data.get('extra_images'))

        _logger.debug(f"Ürün güncellendi: {product.name}")

        return product

    def _handle_zero_stock_product(self, product):
        """Stok 0 olan ürünü işle"""
        self.ensure_one()

        if not product:
            return

        if self._is_reference_locked_product(product):
            if product.exists():
                product.write({'sale_ok': False})
                _logger.info(
                    "Stok 0 - iliskili urun sadece satisa kapatildi: %s",
                    product.name,
                )
            return

        # Ürünün satış geçmişi var mı kontrol et
        has_sales = self.env['sale.order.line'].search_count([
            ('product_id.product_tmpl_id', '=', product.id),
            ('state', 'in', ['sale', 'done']),
        ]) > 0

        if self.delete_unsold_zero_stock and not has_sales:
            # Satışı yok, sil
            product_name = product.name
            try:
                # Ürün hala var mı kontrol et
                if not product.exists():
                    return
                # Önce product.product kayıtlarını sil
                variants = product.product_variant_ids.exists()
                if variants:
                    variants.unlink()
                if product.exists():
                    product.unlink()
                _logger.info(f"Stok 0, satışı yok - ürün silindi: {product_name}")
            except Exception as e:
                _logger.warning(f"Ürün silinemedi ({product_name}): {e}")
                # Silinemezse satışa kapat
                if product.exists():
                    product.write({'sale_ok': False})
        elif self.deactivate_zero_stock:
            # Satışa kapat
            if product.exists():
                product.write({'sale_ok': False})
                _logger.info(f"Stok 0 - ürün satışa kapatıldı: {product.name}")

    # ══════════════════════════════════════════════════════════════════════════
    # CRON
    # ══════════════════════════════════════════════════════════════════════════

    @api.model
    def cron_sync_all_sources(self):
        """Tüm aktif kaynakları senkronize et (Cron job)"""
        sources = self.search([
            ('state', '=', 'active'),
            ('auto_sync', '=', True),
        ])
        _logger.info("CRON: cron_sync_all_sources started - %d sources to check", len(sources))

        for source in sources:
            if source.next_sync and source.next_sync <= fields.Datetime.now():
                _logger.info("CRON: syncing source ID %s - %s", source.id, source.name)
                try:
                    source.action_import_products()
                except Exception as e:
                    _logger.error(f"Cron sync hatası ({source.name}): {e}")

    # ══════════════════════════════════════════════════════════════════════════
    # ACTIONS
    # ══════════════════════════════════════════════════════════════════════════

    def action_view_products(self):
        """Bu kaynaktan gelen ürünleri görüntüle"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ürünler - %s') % self.name,
            'res_model': 'product.template',
            'view_mode': 'list,form',
            'domain': [('xml_source_id', '=', self.id)],
            'context': {'default_xml_source_id': self.id},
        }

    def action_view_logs(self):
        """İçe aktarım loglarını görüntüle"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('İçe Aktarım Logları - %s') % self.name,
            'res_model': 'xml.import.log',
            'view_mode': 'list,form',
            'domain': [('source_id', '=', self.id)],
        }

    def action_activate(self):
        """Kaynağı aktifleştir"""
        self.write({'state': 'active'})

    def action_pause(self):
        """Kaynağı duraklat"""
        self.write({'state': 'paused'})

    def action_reset(self):
        """Kaynağı sıfırla"""
        self.write({
            'state': 'draft',
            'last_error': False,
        })
    def action_apply_dropship_route(self):
        """Tüm XML ürünlerine dropship rotası uygula"""
        self.ensure_one()

        dropship_route = self.env.ref('stock_dropshipping.route_drop_shipping', raise_if_not_found=False)
        if not dropship_route:
            raise UserError(_('Dropship rotası bulunamadı. stock_dropshipping modülü kurulu mu?'))

        products = self.env['product.template'].search([
            ('xml_source_id', '=', self.id),
            ('route_ids', 'not in', [dropship_route.id]),
        ])

        count = 0
        for product in products:
            if dropship_route.id not in product.route_ids.ids:
                product.write({'route_ids': [(4, dropship_route.id)]})
                count += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Dropship Rotası Uygulandı'),
                'message': _('%s ürüne Transit Satış (Dropship) rotası eklendi.') % count,
                'type': 'success',
                'sticky': False,
            }
        }

    def action_sync_suppliers(self):
        """Tüm XML ürünlerine tedarikçi bilgisi ekle"""
        self.ensure_one()

        if not self.supplier_id:
            raise UserError(_('Lütfen önce tedarikçi seçin.'))

        products = self.env['product.template'].search([
            ('xml_source_id', '=', self.id),
        ])

        count = 0
        for product in products:
            # Tedarikçi zaten ekli mi?
            existing = self.env['product.supplierinfo'].search([
                ('product_tmpl_id', '=', product.id),
                ('partner_id', '=', self.supplier_id.id),
            ], limit=1)

            if not existing:
                self.env['product.supplierinfo'].create({
                    'product_tmpl_id': product.id,
                    'partner_id': self.supplier_id.id,
                    'price': product.xml_supplier_price or product.standard_price,
                    'product_code': product.xml_supplier_sku or product.default_code,
                })
                count += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Tedarikçi Senkronize Edildi'),
                'message': _('%s ürüne tedarikçi bilgisi eklendi.') % count,
                'type': 'success',
                'sticky': False,
            }
        }
