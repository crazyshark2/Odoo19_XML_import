# -*- coding: utf-8 -*-

from odoo import models, fields, api
import re


class XmlVariantMapping(models.Model):
    """XML Varyant Özellik Eşleştirmesi - XML varyant değerlerini Odoo attribute değerlerine eşler"""
    _name = 'xml.variant.mapping'
    _description = 'XML Varyant Özellik Eşleştirmesi'
    _order = 'sequence, id'
    _rec_name = 'xml_variant_value'

    source_id = fields.Many2one(
        'xml.product.source',
        string='XML Kaynağı',
        required=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(default=10)

    # Kaynak (XML'den gelen varyant değeri)
    xml_attribute_name = fields.Char(
        string='XML Özellik Adı',
        help='İç içe varyantlarda (<VariantAttributes><Attribute><Name>) gelen özellik adı. '
             'Boş bırakılırsa sadece xml_variant_value ile eşleşme yapılır. '
             'Örn: "Çerçeve", "Cinsiyet"',
    )
    xml_variant_value = fields.Char(
        string='XML Varyant Değeri (Kaynak)',
        required=True,
        help='XML dosyasındaki varyant değeri (örn: "RED", "S", "Mavi", "Köşeli")',
    )

    # Hedef Odoo Attribute
    attribute_id = fields.Many2one(
        'product.attribute',
        string='Özellik (Attribute)',
        required=True,
        help='Odoo ürün özelliği (örn: Renk, Beden)',
    )

    attribute_value_id = fields.Many2one(
        'product.attribute.value',
        string='Özellik Değeri',
        required=True,
        help='Odoo özellik değeri (örn: Kırmızı, Small)',
        domain="[('attribute_id', '=', attribute_id)]",
    )

    # Yeni attribute değeri oluşturmaya izin ver
    allow_create_value = fields.Boolean(
        string='Değer Yoksa Oluştur',
        default=False,
        help='Eşleşen attribute değeri bulunamazsa otomatik oluşturulsun',
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
        ('unique_source_variant_value',
         'UNIQUE(source_id, xml_variant_value)',
         'Aynı XML varyant değeri bu kaynak için zaten tanımlanmış!')
    ]

    @api.model
    def find_mapping(self, source_id, xml_variant_value, xml_attribute_name=None):
        """
        XML varyant değerine göre eşleşen mapping'i bul

        Args:
            source_id: xml.product.source ID
            xml_variant_value: XML'den gelen varyant değeri
            xml_attribute_name: İç içe yapılarda özellik adı (opsiyonel)

        Returns:
            xml.variant.mapping record veya False
        """
        if not xml_variant_value:
            return False

        xml_variant_value = str(xml_variant_value).strip()

        # Önce tam eşleşme ara (attribute adı varsa onunla birlikte)
        domain = [
            ('source_id', '=', source_id),
            ('active', '=', True),
            ('xml_variant_value', '=', xml_variant_value),
            ('match_type', '=', 'exact'),
        ]
        if xml_attribute_name:
            domain += [('xml_attribute_name', '=', xml_attribute_name)]
        else:
            domain += [('xml_attribute_name', '=', False)]

        mapping = self.search(domain, limit=1)

        if mapping:
            return mapping

        # Flat (attribute_name yok) kayıtlarda da ara
        if xml_attribute_name:
            mapping = self.search([
                ('source_id', '=', source_id),
                ('active', '=', True),
                ('xml_variant_value', '=', xml_variant_value),
                ('xml_attribute_name', '=', False),
                ('match_type', '=', 'exact'),
            ], limit=1)
            if mapping:
                return mapping

        # Sonra diğer eşleşme türlerini dene
        domain = [
            ('source_id', '=', source_id),
            ('active', '=', True),
            ('match_type', '!=', 'exact'),
        ]
        if xml_attribute_name:
            domain += [('xml_attribute_name', '=', xml_attribute_name)]
        else:
            domain += [('xml_attribute_name', '=', False)]

        mappings = self.search(domain)

        for m in mappings:
            if m.match_type == 'contains' and m.xml_variant_value in xml_variant_value:
                return m
            elif m.match_type == 'startswith' and xml_variant_value.startswith(m.xml_variant_value):
                return m
            elif m.match_type == 'regex':
                try:
                    if re.match(m.xml_variant_value, xml_variant_value):
                        return m
                except re.error:
                    pass

        return False
