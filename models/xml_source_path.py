# -*- coding: utf-8 -*-

from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class XmlSourcePath(models.Model):
    _name = 'xml.source.path'
    _description = 'XML Kaynak Yolu'
    _rec_name = 'name'
    _order = 'name'

    name = fields.Char(string='Yol', required=True)
    source_id = fields.Many2one(
        'xml.product.source',
        string='XML Kaynağı',
        required=True,
        ondelete='cascade',
    )
    sample_value = fields.Char(string='Örnek Değer')

    _sql_constraints = [
        ('name_source_unique', 'UNIQUE(name, source_id)',
         'Bu yol zaten bu kaynak için eklenmiş!'),
    ]

    @api.model
    def name_create(self, name):
        source_id = self.env.context.get('default_source_id')
        record = self.create({
            'name': name,
            'source_id': source_id or self.env['xml.field.mapping'].browse(
                self.env.context.get('default_mapping_id')
            ).source_id.id,
        })
        return record.name_get()[0]

    @api.model
    def discover_from_source(self, source):
        """XML kaynağından tüm yolları tespit et ve kaydet"""
        self.search([('source_id', '=', source.id)]).unlink()
        try:
            xml_content = source._fetch_xml()
            elements = source._parse_xml(xml_content)
        except Exception:
            return self.env['xml.source.path']

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
                paths[current] = text
            for child in children:
                for k, v in walk(child, current).items():
                    if k not in paths:
                        paths[k] = v
            return paths

        all_paths = OrderedDict()
        for pi in range(min(3, len(elements))):
            el = elements[pi]
            for attr_name, attr_value in (el.attrib or {}).items():
                path = f"@{attr_name}"
                if path not in all_paths:
                    all_paths[path] = attr_value
            for child in list(el):
                for k, v in walk(child).items():
                    if k not in all_paths:
                        all_paths[k] = v

        records = self.env['xml.source.path']
        for path, value in all_paths.items():
            records += records.create({
                'name': path,
                'source_id': source.id,
                'sample_value': (value or '').strip()[:120],
            })
        return records
