# -*- coding: utf-8 -*-

from html import unescape
from odoo import models, fields, api


class XmlCategoryMapping(models.Model):
    """XML Kategori Eşleştirmesi - XML kategorilerini Odoo kategorilerine eşler"""
    _name = 'xml.category.mapping'
    _description = 'XML Kategori Eşleştirmesi'
    _order = 'sequence, xml_category'
    _rec_name = 'xml_category'

    source_id = fields.Many2one(
        'xml.product.source',
        string='XML Kaynağı',
        required=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(default=10)

    # Kaynak (XML'den gelen)
    xml_category = fields.Char(
        string='XML Kategori (Kaynak)',
        required=True,
        help='XML dosyasındaki kategori adı veya yolu (örn: "Elektronik > Telefon")',
    )

    # Hedef Odoo Kategorileri
    odoo_category_id = fields.Many2one(
        'product.category',
        string='Odoo Kategori (Hedef)',
        help='Ürün dahili kategorisi (muhasebe, raporlama için)',
    )

    # E-ticaret Kategorisi (website_sale modülü varsa)
    ecommerce_category_ids = fields.Many2many(
        'product.public.category',
        'xml_category_ecommerce_rel',
        'mapping_id',
        'category_id',
        string='E-Ticaret Kategorileri',
        help='Web sitesinde görünecek kategoriler (birden fazla seçilebilir)',
    )

    # Eşleştirme türü
    match_type = fields.Selection([
        ('exact', 'Tam Eşleşme'),
        ('contains', 'İçerir'),
        ('startswith', 'İle Başlar'),
        ('regex', 'Regex'),
    ], string='Eşleşme Türü', default='exact', required=True)

    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('unique_source_category',
         'UNIQUE(source_id, xml_category)',
         'Aynı XML kategorisi bu kaynak için zaten tanımlanmış!')
    ]

    @api.model
    def find_mapping(self, source_id, xml_category_name):
        """
        XML kategori adına göre eşleşen mapping'i bul

        Args:
            source_id: xml.product.source ID
            xml_category_name: XML'den gelen kategori adı

        Returns:
            xml.category.mapping record veya False
        """
        if not xml_category_name:
            return False

        xml_category_name = unescape(xml_category_name.strip())

        # Önce tam eşleşme ara
        mapping = self.search([
            ('source_id', '=', source_id),
            ('active', '=', True),
            ('xml_category', '=', xml_category_name),
            ('match_type', '=', 'exact'),
        ], limit=1)

        if mapping:
            return mapping

        # Sonra diğer eşleşme türlerini dene
        mappings = self.search([
            ('source_id', '=', source_id),
            ('active', '=', True),
            ('match_type', '!=', 'exact'),
        ])

        import re
        for m in mappings:
            if m.match_type == 'contains' and m.xml_category in xml_category_name:
                return m
            elif m.match_type == 'startswith' and xml_category_name.startswith(m.xml_category):
                return m
            elif m.match_type == 'regex':
                try:
                    if re.match(m.xml_category, xml_category_name):
                        return m
                except re.error:
                    pass

        return False
