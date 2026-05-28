# -*- coding: utf-8 -*-

import logging
import secrets
from lxml import etree

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class XmlProductExport(models.Model):
    """XML Ürün Export Kaynağı - Bayiler için ürün paylaşımı"""
    _name = 'xml.product.export'
    _description = 'XML Ürün Export Kaynağı'
    _order = 'name'

    name = fields.Char(
        string='Kaynak Adı',
        required=True,
        help='Örn: Bayi XML, N11 Entegrasyonu',
    )
    
    active = fields.Boolean(default=True)
    
    # Güvenlik
    access_token = fields.Char(
        string='Erişim Token',
        required=True,
        default=lambda self: secrets.token_urlsafe(32),
        help='XML linkine erişim için güvenlik tokenı',
    )
    
    password = fields.Char(
        string='Şifre (Opsiyonel)',
        help='Ek güvenlik için şifre (URL parametresi olarak)',
    )
    
    # Ürün Filtreleri
    filter_type = fields.Selection([
        ('all', 'Tüm Ürünler'),
        ('category', 'Kategoriye Göre'),
        ('supplier', 'Tedarikçiye Göre'),
        ('manual', 'Manuel Seçim'),
    ], string='Filtre Tipi', default='all', required=True)
    
    category_ids = fields.Many2many(
        'product.category',
        'xml_export_category_rel',
        'export_id', 'category_id',
        string='Kategoriler',
    )
    
    supplier_id = fields.Many2one(
        'res.partner',
        string='Tedarikçi',
        domain=[('supplier_rank', '>', 0)],
    )
    
    product_ids = fields.Many2many(
        'product.template',
        'xml_export_product_rel',
        'export_id', 'product_id',
        string='Manuel Ürünler',
    )
    
    # Stok Ayarları
    include_zero_stock = fields.Boolean(
        string='Stoksuz Ürünleri Dahil Et',
        default=False,
    )
    
    min_stock = fields.Integer(
        string='Minimum Stok',
        default=0,
        help='Bu miktarın altındaki ürünler dahil edilmez',
    )
    
    # Fiyat Ayarları
    price_field = fields.Selection([
        ('list_price', 'Satış Fiyatı'),
        ('standard_price', 'Maliyet'),
        ('xml_supplier_price', 'Tedarikçi Fiyatı'),
    ], string='Fiyat Alanı', default='list_price', required=True)
    
    price_markup_type = fields.Selection([
        ('none', 'Değişiklik Yok'),
        ('percent', 'Yüzde Artış'),
        ('percent_discount', 'Yüzde İndirim'),
        ('fixed', 'Sabit Artış'),
        ('fixed_discount', 'Sabit İndirim'),
    ], string='Fiyat Düzenleme', default='none')
    
    price_markup_value = fields.Float(
        string='Düzenleme Değeri',
        help='Yüzde veya sabit tutar',
    )
    
    currency_id = fields.Many2one(
        'res.currency',
        string='Para Birimi',
        default=lambda self: self.env.company.currency_id,
    )
    
    # XML Format Ayarları
    xml_format = fields.Selection([
        ('standard', 'Standart Format'),
        ('tsoft', 'T-Soft Format'),
        ('ticimax', 'Ticimax Format'),
        ('n11', 'N11 Format'),
        ('hepsiburada', 'Hepsiburada Format'),
        ('custom', 'Özel Format'),
    ], string='XML Formatı', default='standard', required=True)
    
    root_element = fields.Char(
        string='Kök Element',
        default='products',
    )
    
    product_element = fields.Char(
        string='Ürün Element',
        default='product',
    )
    
    include_images = fields.Boolean(
        string='Görselleri Dahil Et',
        default=True,
    )
    
    include_description = fields.Boolean(
        string='Açıklamayı Dahil Et',
        default=True,
    )
    
    include_variants = fields.Boolean(
        string='Varyantları Dahil Et',
        default=False,
    )
    
    # Alan Eşleştirme
    field_mapping_ids = fields.One2many(
        'xml.export.field.mapping',
        'export_id',
        string='Alan Eşleştirmeleri',
    )
    
    # İstatistikler
    product_count = fields.Integer(
        string='Ürün Sayısı',
        compute='_compute_product_count',
    )
    
    last_access = fields.Datetime(
        string='Son Erişim',
        readonly=True,
    )
    
    access_count = fields.Integer(
        string='Erişim Sayısı',
        default=0,
        readonly=True,
    )
    
    xml_url = fields.Char(
        string='XML Link',
        compute='_compute_xml_url',
    )

    @api.depends('access_token', 'password')
    def _compute_xml_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for rec in self:
            url = f"{base_url}/xml/export/{rec.access_token}"
            if rec.password:
                url += f"?pass={rec.password}"
            rec.xml_url = url

    def _compute_product_count(self):
        for rec in self:
            rec.product_count = len(rec._get_products())

    def action_regenerate_token(self):
        """Token'ı yeniden oluştur"""
        self.access_token = secrets.token_urlsafe(32)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Token Yenilendi'),
                'message': _('Yeni erişim tokenı oluşturuldu.'),
                'type': 'success',
            }
        }

    def action_copy_url(self):
        """URL'yi kopyala (JS ile)"""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('XML Link'),
                'message': self.xml_url,
                'type': 'info',
                'sticky': True,
            }
        }

    def action_preview_xml(self):
        """XML önizleme"""
        return {
            'type': 'ir.actions.act_url',
            'url': self.xml_url,
            'target': 'new',
        }

    def action_view_products(self):
        """Export edilecek ürünleri görüntüle"""
        products = self._get_products()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Export Ürünleri'),
            'res_model': 'product.template',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', products.ids)],
        }

    def _get_products(self):
        """Filtre kriterlerine göre ürünleri getir"""
        self.ensure_one()
        
        domain = [('sale_ok', '=', True)]
        
        # Stok filtresi
        if not self.include_zero_stock:
            # TODO: Stok kontrolü için daha iyi bir yöntem
            pass
        
        if self.filter_type == 'all':
            pass
        elif self.filter_type == 'category' and self.category_ids:
            # Alt kategorileri de dahil et
            all_categ_ids = self.category_ids.ids
            for categ in self.category_ids:
                all_categ_ids.extend(categ.search([('parent_id', 'child_of', categ.id)]).ids)
            domain.append(('categ_id', 'in', list(set(all_categ_ids))))
        elif self.filter_type == 'supplier' and self.supplier_id:
            domain.append(('seller_ids.partner_id', '=', self.supplier_id.id))
        elif self.filter_type == 'manual' and self.product_ids:
            domain.append(('id', 'in', self.product_ids.ids))
        
        products = self.env['product.template'].search(domain)
        
        # Stok filtresi (hesaplanmış)
        if not self.include_zero_stock:
            products = products.filtered(lambda p: p.qty_available > self.min_stock)
        
        return products

    def _calculate_price(self, product):
        """Ürün fiyatını hesapla"""
        self.ensure_one()
        
        # Temel fiyatı al
        if self.price_field == 'list_price':
            price = product.list_price
        elif self.price_field == 'standard_price':
            price = product.standard_price
        elif self.price_field == 'xml_supplier_price':
            price = getattr(product, 'xml_supplier_price', 0) or product.standard_price
        else:
            price = product.list_price
        
        # Fiyat düzenlemesi
        if self.price_markup_type == 'percent':
            price = price * (1 + self.price_markup_value / 100)
        elif self.price_markup_type == 'percent_discount':
            price = price * (1 - self.price_markup_value / 100)
        elif self.price_markup_type == 'fixed':
            price = price + self.price_markup_value
        elif self.price_markup_type == 'fixed_discount':
            price = price - self.price_markup_value
        
        return round(price, 2)

    def _get_product_image_url(self, product):
        """Ürün görsel URL'sini al"""
        # Önce XML görsel URL'sini kontrol et
        if hasattr(product, 'xml_image_url') and product.xml_image_url:
            return product.xml_image_url
        
        # Yoksa Odoo görselini URL olarak döndür
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        if product.image_1920:
            return f"{base_url}/web/image/product.template/{product.id}/image_1920"
        
        return ''

    def _get_extra_image_urls(self, product):
        """Ek görsel URL'lerini al"""
        urls = []
        
        # XML ek görselleri
        if hasattr(product, 'xml_image_urls') and product.xml_image_urls:
            urls.extend([u.strip() for u in product.xml_image_urls.split('\n') if u.strip()])
        
        # Odoo product.image kayıtları
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for img in product.product_template_image_ids:
            urls.append(f"{base_url}/web/image/product.image/{img.id}/image_1920")
        
        return urls

    def generate_xml(self):
        """XML çıktısı oluştur"""
        self.ensure_one()
        
        products = self._get_products()
        
        # Erişim kaydı
        self.sudo().write({
            'last_access': fields.Datetime.now(),
            'access_count': self.access_count + 1,
        })
        
        # Formata göre XML oluştur
        if self.xml_format == 'tsoft':
            return self._generate_tsoft_xml(products)
        elif self.xml_format == 'ticimax':
            return self._generate_ticimax_xml(products)
        elif self.xml_format == 'n11':
            return self._generate_n11_xml(products)
        elif self.xml_format == 'hepsiburada':
            return self._generate_hepsiburada_xml(products)
        else:
            return self._generate_standard_xml(products)

    def _generate_standard_xml(self, products):
        """Standart XML formatı"""
        root = etree.Element(self.root_element or 'products')
        
        for product in products:
            prod_elem = etree.SubElement(root, self.product_element or 'product')
            
            # Temel alanlar
            etree.SubElement(prod_elem, 'id').text = str(product.id)
            etree.SubElement(prod_elem, 'code').text = product.default_code or ''
            etree.SubElement(prod_elem, 'barcode').text = product.barcode or ''
            etree.SubElement(prod_elem, 'name').text = product.name or ''
            
            # Kategori
            if product.categ_id:
                etree.SubElement(prod_elem, 'category').text = product.categ_id.complete_name or ''
            
            # Fiyat
            price = self._calculate_price(product)
            etree.SubElement(prod_elem, 'price').text = str(price)
            etree.SubElement(prod_elem, 'currency').text = self.currency_id.name or 'TRY'
            
            # KDV
            tax_rate = 0
            if product.taxes_id:
                tax_rate = product.taxes_id[0].amount if product.taxes_id else 0
            etree.SubElement(prod_elem, 'vat').text = str(int(tax_rate))
            
            # Stok
            etree.SubElement(prod_elem, 'stock').text = str(int(product.qty_available))
            
            # Marka
            if hasattr(product, 'product_brand_id') and product.product_brand_id:
                etree.SubElement(prod_elem, 'brand').text = product.product_brand_id.name or ''
            
            # Açıklama
            if self.include_description:
                desc = product.description_sale or product.description or ''
                desc_elem = etree.SubElement(prod_elem, 'description')
                desc_elem.text = etree.CDATA(str(desc))
            
            # Görsel
            if self.include_images:
                image_url = self._get_product_image_url(product)
                if image_url:
                    etree.SubElement(prod_elem, 'image').text = image_url
                
                # Ek görseller
                extra_urls = self._get_extra_image_urls(product)
                if extra_urls:
                    images_elem = etree.SubElement(prod_elem, 'images')
                    for url in extra_urls[:10]:
                        etree.SubElement(images_elem, 'img').text = url
            
            # Ağırlık ve boyut
            if product.weight:
                etree.SubElement(prod_elem, 'weight').text = str(product.weight)
            if hasattr(product, 'deci') and product.deci:
                etree.SubElement(prod_elem, 'deci').text = str(product.deci)
            
            # Özel alan eşleştirmeleri
            for mapping in self.field_mapping_ids:
                value = mapping._get_field_value(product)
                if value:
                    elem = etree.SubElement(prod_elem, mapping.xml_element)
                    if mapping.use_cdata:
                        elem.text = etree.CDATA(str(value))
                    else:
                        elem.text = str(value)
        
        xml_string = etree.tostring(
            root, 
            pretty_print=True, 
            xml_declaration=True, 
            encoding='UTF-8'
        )
        
        return xml_string.decode('utf-8')

    def _generate_tsoft_xml(self, products):
        """T-Soft uyumlu XML formatı"""
        root = etree.Element('products')
        
        for product in products:
            prod_elem = etree.SubElement(root, 'product')
            
            etree.SubElement(prod_elem, 'code').text = str(product.id)
            etree.SubElement(prod_elem, 'ws_code').text = product.default_code or ''
            
            barcode_elem = etree.SubElement(prod_elem, 'barcode')
            barcode_elem.text = etree.CDATA(product.barcode or '')
            
            name_elem = etree.SubElement(prod_elem, 'name')
            name_elem.text = etree.CDATA(product.name or '')
            
            # Kategori yolu
            if product.categ_id:
                cat_path_elem = etree.SubElement(prod_elem, 'category_path')
                cat_path_elem.text = etree.CDATA(product.categ_id.complete_name.replace(' / ', ' > '))
            
            # Stok ve fiyat
            etree.SubElement(prod_elem, 'stock').text = str(int(product.qty_available))
            etree.SubElement(prod_elem, 'unit').text = product.uom_id.name if product.uom_id else 'ADET'
            
            price = self._calculate_price(product)
            tax_rate = product.taxes_id[0].amount if product.taxes_id else 0
            price_with_vat = price * (1 + tax_rate / 100)
            
            etree.SubElement(prod_elem, 'price_list').text = str(round(price, 2))
            etree.SubElement(prod_elem, 'price_list_vat_included').text = str(round(price_with_vat, 2))
            etree.SubElement(prod_elem, 'currency').text = self.currency_id.name or 'TL'
            etree.SubElement(prod_elem, 'vat').text = str(int(tax_rate))
            
            # Marka
            if hasattr(product, 'product_brand_id') and product.product_brand_id:
                brand_elem = etree.SubElement(prod_elem, 'brand')
                brand_elem.text = etree.CDATA(product.product_brand_id.name or '')
            
            # Desi/ağırlık
            etree.SubElement(prod_elem, 'desi').text = str(getattr(product, 'deci', 0) or 0)
            etree.SubElement(prod_elem, 'weight').text = str(product.weight or 0)
            
            # Açıklama
            if self.include_description:
                detail_elem = etree.SubElement(prod_elem, 'detail')
                desc = product.description_sale or product.description or ''
                detail_elem.text = etree.CDATA(str(desc))
            
            # Görseller
            if self.include_images:
                images_elem = etree.SubElement(prod_elem, 'images')
                
                main_url = self._get_product_image_url(product)
                if main_url:
                    img_elem = etree.SubElement(images_elem, 'img_item')
                    img_elem.text = etree.CDATA(main_url)
                
                for url in self._get_extra_image_urls(product)[:9]:
                    img_elem = etree.SubElement(images_elem, 'img_item')
                    img_elem.text = etree.CDATA(url)
        
        xml_string = etree.tostring(
            root, 
            pretty_print=True, 
            xml_declaration=True, 
            encoding='UTF-8'
        )
        
        return xml_string.decode('utf-8')

    def _generate_ticimax_xml(self, products):
        """Ticimax uyumlu XML formatı"""
        root = etree.Element('Products')
        
        for product in products:
            prod_elem = etree.SubElement(root, 'Product')
            
            etree.SubElement(prod_elem, 'ProductId').text = str(product.id)
            etree.SubElement(prod_elem, 'ProductCode').text = product.default_code or ''
            etree.SubElement(prod_elem, 'Barcode').text = product.barcode or ''
            etree.SubElement(prod_elem, 'ProductName').text = product.name or ''
            
            if product.categ_id:
                etree.SubElement(prod_elem, 'CategoryName').text = product.categ_id.name or ''
                etree.SubElement(prod_elem, 'CategoryPath').text = product.categ_id.complete_name or ''
            
            price = self._calculate_price(product)
            etree.SubElement(prod_elem, 'Price').text = str(price)
            etree.SubElement(prod_elem, 'Stock').text = str(int(product.qty_available))
            
            if hasattr(product, 'product_brand_id') and product.product_brand_id:
                etree.SubElement(prod_elem, 'Brand').text = product.product_brand_id.name or ''
            
            if self.include_description:
                etree.SubElement(prod_elem, 'Description').text = product.description_sale or ''
            
            if self.include_images:
                images_elem = etree.SubElement(prod_elem, 'Images')
                main_url = self._get_product_image_url(product)
                if main_url:
                    img_elem = etree.SubElement(images_elem, 'Image')
                    etree.SubElement(img_elem, 'Url').text = main_url
                    etree.SubElement(img_elem, 'Order').text = '1'
        
        return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding='UTF-8').decode('utf-8')

    def _generate_n11_xml(self, products):
        """N11 uyumlu XML formatı"""
        root = etree.Element('Products')
        
        for product in products:
            prod_elem = etree.SubElement(root, 'Product')
            
            etree.SubElement(prod_elem, 'productSellerCode').text = product.default_code or str(product.id)
            etree.SubElement(prod_elem, 'title').text = product.name or ''
            etree.SubElement(prod_elem, 'subtitle').text = ''
            
            price = self._calculate_price(product)
            etree.SubElement(prod_elem, 'price').text = str(price)
            etree.SubElement(prod_elem, 'currencyType').text = '1' if self.currency_id.name == 'TRY' else '2'
            
            if product.categ_id:
                etree.SubElement(prod_elem, 'category').text = product.categ_id.name or ''
            
            etree.SubElement(prod_elem, 'stockAmount').text = str(int(product.qty_available))
            
            if self.include_description:
                etree.SubElement(prod_elem, 'description').text = product.description_sale or ''
            
            if self.include_images:
                images_elem = etree.SubElement(prod_elem, 'images')
                main_url = self._get_product_image_url(product)
                if main_url:
                    img_elem = etree.SubElement(images_elem, 'image')
                    etree.SubElement(img_elem, 'url').text = main_url
                    etree.SubElement(img_elem, 'order').text = '1'
        
        return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding='UTF-8').decode('utf-8')

    def _generate_hepsiburada_xml(self, products):
        """Hepsiburada uyumlu XML formatı"""
        root = etree.Element('Products')
        
        for product in products:
            prod_elem = etree.SubElement(root, 'Product')
            
            etree.SubElement(prod_elem, 'MerchantSku').text = product.default_code or str(product.id)
            etree.SubElement(prod_elem, 'Barcode').text = product.barcode or ''
            etree.SubElement(prod_elem, 'ProductName').text = product.name or ''
            
            price = self._calculate_price(product)
            etree.SubElement(prod_elem, 'Price').text = str(price)
            etree.SubElement(prod_elem, 'AvailableStock').text = str(int(product.qty_available))
            
            if hasattr(product, 'product_brand_id') and product.product_brand_id:
                etree.SubElement(prod_elem, 'Brand').text = product.product_brand_id.name or ''
            
            if self.include_description:
                etree.SubElement(prod_elem, 'Description').text = product.description_sale or ''
            
            if self.include_images:
                main_url = self._get_product_image_url(product)
                if main_url:
                    etree.SubElement(prod_elem, 'Image1').text = main_url
                
                extra_urls = self._get_extra_image_urls(product)
                for i, url in enumerate(extra_urls[:4], start=2):
                    etree.SubElement(prod_elem, f'Image{i}').text = url
        
        return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding='UTF-8').decode('utf-8')


class XmlExportFieldMapping(models.Model):
    """XML Export Alan Eşleştirme"""
    _name = 'xml.export.field.mapping'
    _description = 'XML Export Alan Eşleştirme'
    _order = 'sequence'

    export_id = fields.Many2one(
        'xml.product.export',
        string='Export Kaynağı',
        required=True,
        ondelete='cascade',
    )
    
    sequence = fields.Integer(default=10)
    
    name = fields.Char(
        string='Alan Adı',
        required=True,
    )
    
    odoo_field = fields.Char(
        string='Odoo Alanı',
        required=True,
        help='Örn: default_code, name, list_price, categ_id.name',
    )
    
    xml_element = fields.Char(
        string='XML Element',
        required=True,
        help='XML çıktısında kullanılacak element adı',
    )
    
    use_cdata = fields.Boolean(
        string='CDATA Kullan',
        default=False,
        help='HTML içerik için CDATA kullan',
    )
    
    default_value = fields.Char(
        string='Varsayılan Değer',
        help='Alan boşsa kullanılacak değer',
    )

    def _get_field_value(self, product):
        """Üründen alan değerini al"""
        self.ensure_one()
        
        try:
            field_path = self.odoo_field.split('.')
            value = product
            
            for field in field_path:
                if hasattr(value, field):
                    value = getattr(value, field)
                else:
                    value = None
                    break
            
            if value is None or value == '':
                return self.default_value
            
            return value
            
        except Exception as e:
            _logger.warning(f"Alan değeri alınamadı: {self.odoo_field} - {e}")
            return self.default_value
