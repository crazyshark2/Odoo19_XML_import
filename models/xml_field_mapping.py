# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
import re
import logging

_logger = logging.getLogger(__name__)


class XmlFieldMapping(models.Model):
    """XML Alan Eşleştirmesi"""
    _name = 'xml.field.mapping'
    _description = 'XML Alan Eşleştirmesi'
    _order = 'sequence, id'

    source_id = fields.Many2one(
        'xml.product.source',
        string='XML Kaynağı',
        required=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(default=10)
    
    odoo_field = fields.Selection([
        ('sku', 'Ürün Kodu (SKU)'),
        ('barcode', 'Barkod'),
        ('name', 'Ürün Adı'),
        ('description', 'Açıklama'),
        ('description_short', 'Kısa Açıklama'),
        ('price', 'Satış Fiyatı'),
        ('cost_price', 'Maliyet/Tedarikçi Fiyatı'),
        ('stock', 'Stok Miktarı'),
        ('category', 'Kategori'),
        ('brand', 'Marka'),
        ('image', 'Görsel URL (Ana)'),
        ('image2', 'Görsel URL 2'),
        ('image3', 'Görsel URL 3'),
        ('image4', 'Görsel URL 4'),
        ('images', 'Tüm Görseller (Liste)'),
        ('weight', 'Ağırlık (kg)'),
        ('deci', 'Desi'),
        ('warranty', 'Garanti'),
        ('model', 'Model'),
        ('color', 'Renk'),
        ('size', 'Beden/Boyut'),
        ('currency', 'Para Birimi'),
        ('tax', 'KDV Oranı'),
        ('origin', 'Menşei'),
        ('supplier_sku', 'Tedarikçi Stok Kodu'),
        ('external_product_id', 'Harici Ürün ID'),
        ('source_stock_id', 'Harici Stok ID'),
        ('usage_class', 'Kullanım Sınıfı'),
        ('variant_group', 'Varyant Grubu'),
        ('variant_attribute', 'Varyant Özellik Değeri'),
        ('extra1', 'Ekstra Alan 1'),
        ('extra2', 'Ekstra Alan 2'),
        ('extra3', 'Ekstra Alan 3'),
    ], string='Odoo Alanı', required=True)
    
    variant_attribute_id = fields.Many2one(
        'product.attribute',
        string='Varyant Özelliği',
        help='"Varyant Özellik Değeri" seçiliyse hangi Odoo özelliğine ait olduğunu belirtir. '
             'Örn: "Renk" seçilirse XML\'deki değer (KIRMIZI) Renk özelliğinin değeri olarak işlenir.',
    )
    variant_name_subpath = fields.Char(
        string='Özellik Adı Alt Yolu',
        help='İç içe varyantlarda (<VariantAttributes><Attribute>) özellik adını içeren alt element. '
             'Örn: <Attribute><Name>Çerçeve</Name> ise "Name" yazın.',
    )
    variant_value_subpath = fields.Char(
        string='Özellik Değeri Alt Yolu',
        help='İç içe varyantlarda (<VariantAttributes><Attribute>) özellik değerini içeren alt element. '
             'Örn: <Attribute><Value>Köşeli</Value> ise "Value" yazın.',
    )
    variant_mapping_count = fields.Integer(
        string='Varyant Eşleştirme',
        compute='_compute_variant_mapping_count',
        help='Bu alan eşleştirmesi ile ilgili varyant eşleştirme kayıt sayısı',
    )

    def _compute_variant_mapping_count(self):
        for rec in self:
            if rec.odoo_field == 'variant_attribute':
                domain = [('source_id', '=', rec.source_id.id)]
                if rec.variant_attribute_id:
                    domain.append(('attribute_id', '=', rec.variant_attribute_id.id))
                elif rec.variant_name_subpath:
                    domain.append(('xml_attribute_name', '!=', False))
                else:
                    rec.variant_mapping_count = 0
                    continue
                count = self.env['xml.variant.mapping'].search_count(domain)
                rec.variant_mapping_count = count
            else:
                rec.variant_mapping_count = 0
    
    xml_path = fields.Char(
        string='XML Yolu',
        required=True,
        help='XML yolunu yazın. Örn: ProductCode, Category/Name, @id, Images/Image[1]',
    )
    xml_path_select = fields.Many2one(
        'xml.source.path',
        string='XML Yolu Seç',
        domain="[('source_id', '=', source_id)]",
        help='Keşfedilen yollardan seçin veya yenisini yazın.',
    )

    @api.onchange('xml_path_select')
    def _onchange_xml_path_select(self):
        if self.xml_path_select:
            self.xml_path = self.xml_path_select.name

    def action_select_path(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'select.path.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_mapping_id': self.id,
                'default_source_id': self.source_id.id,
            },
        }

    # Dönüşüm
    transform = fields.Selection([
        ('none', 'Dönüşüm Yok'),
        ('uppercase', 'BÜYÜK HARF'),
        ('lowercase', 'küçük harf'),
        ('titlecase', 'Başlık Formatı'),
        ('strip', 'Boşlukları Temizle'),
        ('number', 'Sayıya Çevir'),
        ('price', 'Fiyat Formatı (1.234,56 → 1234.56)'),
        ('html_strip', 'HTML Etiketlerini Kaldır'),
        ('regex', 'Regex ile Temizle'),
    ], string='Dönüşüm', default='none')
    
    regex_pattern = fields.Char(
        string='Regex Pattern',
        help='Dönüşüm "regex" seçiliyse kullanılacak pattern',
    )
    regex_replace = fields.Char(
        string='Regex Replace',
        default='',
        help='Regex ile değiştirilecek değer',
    )
    
    default_value = fields.Char(
        string='Varsayılan Değer',
        help='Alan boşsa kullanılacak değer',
    )
    
    is_required = fields.Boolean(
        string='Zorunlu',
        help='Bu alan boşsa ürün atlanır',
    )

    def action_detect_variants_for_attribute(self):
        """Bu alan eşleştirmesindeki varyant değerlerini tespit edip eşleştirme tablosuna ekle"""
        self.ensure_one()
        if self.odoo_field != 'variant_attribute' or not self.variant_attribute_id:
            raise UserError(_('Bu işlem için alan tipi "Varyant Özellik Değeri" ve özellik seçilmiş olmalıdır.'))
        return self.source_id.action_detect_variant_values()

    def apply_transform(self, value):
        """Değere dönüşüm uygula"""
        self.ensure_one()
        
        if not value:
            return self.default_value or value
        
        value = str(value).strip()
        
        if self.transform == 'uppercase':
            value = value.upper()
        
        elif self.transform == 'lowercase':
            value = value.lower()
        
        elif self.transform == 'titlecase':
            value = value.title()
        
        elif self.transform == 'strip':
            value = ' '.join(value.split())
        
        elif self.transform == 'number':
            # Sadece rakamları al
            value = re.sub(r'[^\d.,]', '', value)
            value = value.replace(',', '.')
            try:
                value = str(float(value))
            except (ValueError, TypeError):
                pass
        
        elif self.transform == 'price':
            # Türkçe fiyat formatı: 1.234,56 → 1234.56
            value = value.replace('.', '').replace(',', '.')
            try:
                value = str(float(value))
            except (ValueError, TypeError):
                pass
        
        elif self.transform == 'html_strip':
            # HTML etiketlerini kaldır
            value = re.sub(r'<[^>]+>', '', value)
            value = ' '.join(value.split())
        
        elif self.transform == 'regex' and self.regex_pattern:
            try:
                value = re.sub(self.regex_pattern, self.regex_replace or '', value)
            except re.error:
                pass
        
        return str(value or self.default_value or '')
