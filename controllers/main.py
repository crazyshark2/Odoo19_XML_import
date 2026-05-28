# -*- coding: utf-8 -*-

import logging
from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class XmlExportController(http.Controller):
    """XML Ürün Export Controller - Bayiler için XML çıktısı"""

    @http.route('/xml/export/<string:token>', type='http', auth='public', methods=['GET'], csrf=False)
    def export_xml(self, token, **kwargs):
        """
        Token ile XML export
        URL: /xml/export/<token>?pass=<password>
        """
        try:
            # Token ile export kaynağını bul
            export_source = request.env['xml.product.export'].sudo().search([
                ('access_token', '=', token),
                ('active', '=', True),
            ], limit=1)
            
            if not export_source:
                _logger.warning(f"XML Export: Geçersiz token - {token}")
                return Response(
                    '<?xml version="1.0" encoding="UTF-8"?><error>Invalid token</error>',
                    content_type='application/xml',
                    status=401
                )
            
            # Şifre kontrolü
            if export_source.password:
                provided_pass = kwargs.get('pass', '')
                if provided_pass != export_source.password:
                    _logger.warning(f"XML Export: Yanlış şifre - {export_source.name}")
                    return Response(
                        '<?xml version="1.0" encoding="UTF-8"?><error>Invalid password</error>',
                        content_type='application/xml',
                        status=401
                    )
            
            # XML oluştur
            xml_content = export_source.generate_xml()
            
            _logger.info(f"XML Export başarılı: {export_source.name} - {export_source.product_count} ürün")
            
            return Response(
                xml_content,
                content_type='application/xml; charset=utf-8',
                headers={
                    'Content-Disposition': f'inline; filename="{export_source.name}.xml"',
                    'Cache-Control': 'no-cache, no-store, must-revalidate',
                }
            )
            
        except Exception as e:
            _logger.error(f"XML Export hatası: {e}")
            return Response(
                f'<?xml version="1.0" encoding="UTF-8"?><error>{str(e)}</error>',
                content_type='application/xml',
                status=500
            )

    @http.route('/xml/export/<string:token>/info', type='http', auth='public', methods=['GET'], csrf=False)
    def export_info(self, token, **kwargs):
        """
        Export kaynağı bilgisi (JSON)
        """
        try:
            export_source = request.env['xml.product.export'].sudo().search([
                ('access_token', '=', token),
                ('active', '=', True),
            ], limit=1)
            
            if not export_source:
                return Response(
                    '{"error": "Invalid token"}',
                    content_type='application/json',
                    status=401
                )
            
            # Şifre kontrolü
            if export_source.password:
                provided_pass = kwargs.get('pass', '')
                if provided_pass != export_source.password:
                    return Response(
                        '{"error": "Invalid password"}',
                        content_type='application/json',
                        status=401
                    )
            
            import json
            info = {
                'name': export_source.name,
                'format': export_source.xml_format,
                'product_count': export_source.product_count,
                'last_access': export_source.last_access.isoformat() if export_source.last_access else None,
                'access_count': export_source.access_count,
                'currency': export_source.currency_id.name,
            }
            
            return Response(
                json.dumps(info, ensure_ascii=False),
                content_type='application/json; charset=utf-8'
            )
            
        except Exception as e:
            return Response(
                f'{{"error": "{str(e)}"}}',
                content_type='application/json',
                status=500
            )
