# -*- coding: utf-8 -*-
"""
This 'sphinxcontrib_seqdiag' module is EXPERIMENTAL yet.
"""
import posixpath
import os
import codecs
try:
    from hashlib import sha1 as sha
except ImportError:
    from sha import sha

from docutils import nodes
from docutils.parsers.rst import directives

from sphinx.errors import SphinxError
from sphinx.util.osutil import ensuredir, ENOENT, EPIPE
from sphinx.util.compat import Directive

from seqdiag.seqdiag import *
from blockdiag.diagparser import parse, tokenize

class SeqdiagError(SphinxError):
    category = 'Seqdiag error'


class seqdiag(nodes.General, nodes.Element):
    pass


class Seqdiag(Directive):
    """
    Directive to insert arbitrary dot markup.
    """
    has_content = True
    required_arguments = 0
    optional_arguments = 1
    final_argument_whitespace = False
    option_spec = {
        'alt': directives.unchanged,
        'desctable': directives.flag,
        'maxwidth': directives.nonnegative_int,
    }

    def run(self):
        if self.arguments:
            document = self.state.document
            if self.content:
                return [document.reporter.warning(
                    'seqdiag directive cannot have both content and '
                    'a filename argument', line=self.lineno)]
            env = self.state.document.settings.env
            rel_filename, filename = relfn2path(env, self.arguments[0])
            env.note_dependency(rel_filename)
            try:
                fp = codecs.open(filename, 'r', 'utf-8')
                try:
                    dotcode = fp.read()
                finally:
                    fp.close()
            except (IOError, OSError):
                return [document.reporter.warning(
                    'External seqdiag file %r not found or reading '
                    'it failed' % filename, line=self.lineno)]
        else:
            dotcode = '\n'.join(self.content)
            if not dotcode.strip():
                return [self.state_machine.reporter.warning(
                    'Ignoring "seqdiag" directive without content.',
                    line=self.lineno)]

        node = seqdiag()
        node['code'] = dotcode
        node['options'] = {}
        if 'alt' in self.options:
            node['alt'] = self.options['alt']
        if 'maxwidth' in self.options:
            node['options']['maxwidth'] = self.options['maxwidth']
        if 'desctable' in self.options:
            node['options']['desctable'] = self.options['desctable']
        return [node]


# compatibility to sphinx 1.0 (ported from sphinx trunk)
def relfn2path(env, filename, docname=None):
    if filename.startswith('/') or filename.startswith(os.sep):
        rel_fn = filename[1:]
    else:
        docdir = os.path.dirname(env.doc2path(docname or env.docname,
                                              base=None))
        rel_fn = os.path.join(docdir, filename)
    try:
        return rel_fn, os.path.join(env.srcdir, rel_fn)
    except UnicodeDecodeError:
        # the source directory is a bytestring with non-ASCII characters;
        # let's try to encode the rel_fn in the file system encoding
        enc_rel_fn = rel_fn.encode(sys.getfilesystemencoding())
        return rel_fn, os.path.join(env.srcdir, enc_rel_fn)


def get_image_filename(self, code, options, prefix='seqdiag'):
    """
    Get path of output file.
    """
    hashkey = code.encode('utf-8') + str(options)
    fname = '%s-%s.png' % (prefix, sha(hashkey).hexdigest())
    if hasattr(self.builder, 'imgpath'):
        # HTML
        relfn = posixpath.join(self.builder.imgpath, fname)
        outfn = os.path.join(self.builder.outdir, '_images', fname)
    else:
        # LaTeX
        relfn = fname
        outfn = os.path.join(self.builder.outdir, fname)

    if os.path.isfile(outfn):
        return relfn, outfn

    ensuredir(os.path.dirname(outfn))

    return relfn, outfn


def create_seqdiag(self, code, options, prefix='seqdiag'):
    """
    Render seqdiag code into a PNG output file.
    """
    ttfont = None
    fontpath = self.builder.config.seqdiag_fontpath
    if fontpath and not hasattr(self.builder, '_seqdiag_fontpath_warned'):
        if not os.path.isfile(fontpath):
            self.builder.warn('seqdiag cannot load "%s" as truetype font, '
                              'check the seqdiag_path setting' % fontpath)
            self.builder._seqdiag_fontpath_warned = True

    draw = None
    try:
        antialias = self.builder.config.seqdiag_antialias

        tree = parse(tokenize(code))
        diagram = DiagramTreeBuilder().build(tree)
        draw = DiagramDraw('PNG', diagram, font=fontpath,
                           antialias=antialias)
        draw.draw()
    except Exception, e:
        raise SeqdiagError('seqdiag error:\n%s\n' % e)

    return draw


def render_dot_html(self, node, code, options, prefix='seqdiag',
                    imgcls=None, alt=None):
    has_thumbnail = False
    try:
        relfn, outfn = get_image_filename(self, code, options, prefix)

        image = create_seqdiag(self, code, options, prefix)
        image.save(outfn, 'PNG')

        # generate description table
        descriptions = []
        if 'desctable' in options:
            for n in image.screen.nodes:
                if n.description:
                    descriptions.append((n.id, n.numbered, n.description))

        # generate thumbnails
        image_size = image.drawer.image.size
        if 'maxwidth' in options and options['maxwidth'] < image_size[0]:
            has_thumbnail = True
            thumb_prefix = prefix + '_thumb'
            trelfn, toutfn = get_image_filename(self, code,
                                                options, thumb_prefix)

            thumb_size = (options['maxwidth'], image_size[1])
            image.save(toutfn, 'PNG', thumb_size)
            thumb_size = image.image.size

    except SeqdiagError, exc:
        self.builder.warn('dot code %r: ' % code + str(exc))
        raise nodes.SkipNode

    self.body.append(self.starttag(node, 'p', CLASS='seqdiag'))
    if relfn is None:
        self.body.append(self.encode(code))
    else:
        if alt is None:
            alt = node.get('alt', self.encode(code).strip())

        imgtag_format = '<img src="%s" alt="%s" width="%s" height="%s" />\n'
        if has_thumbnail:
            self.body.append('<a href="%s">' % relfn)
            self.body.append(imgtag_format %
                             (trelfn, alt, thumb_size[0], thumb_size[1]))
            self.body.append('</a>')
        else:
            self.body.append(imgtag_format %
                             (relfn, alt, image_size[0], image_size[1]))

    if descriptions:
        numbered = [x for x in descriptions if x[1]]

        self.body.append('<table border="1" class="docutils">')
        self.body.append('<thead valign="bottom">')
        if numbered:
            self.body.append('<tr><th class="head">No</th><th class="head">Name</th><th class="head">Description</th></tr>')
        else:
            self.body.append('<tr><th class="head">Name</th><th class="head">Description</th></tr>')
        self.body.append('</thead>')
        self.body.append('<tbody valign="top">')

        if numbered:
            def cmp_number(a, b):
                if a[1]:
                    n1 = int(a[1])
                else:
                    n1 = 0

                if b[1]:
                    n2 = int(b[1])
                else:
                    n2 = 0

                return cmp(n1, n2)

            descriptions.sort(cmp_number)

        for desc in descriptions:
            id, number, text = desc
            self.body.append('<tr>')
            if numbered:
                if number is not None:
                    self.body.append('<td>%s</td>' % number)
                else:
                    self.body.append('<td></td>')
            self.body.append('<td>%s</td>' % id)
            self.body.append('<td>%s</td>' % text)
            self.body.append('</tr>')

        self.body.append('</tbody>')
        self.body.append('</table>')

    self.body.append('</p>\n')
    raise nodes.SkipNode


def html_visit_seqdiag(self, node):
    render_dot_html(self, node, node['code'], node['options'])


def render_dot_latex(self, node, code, options, prefix='sdedit'):
    try:
        fname, outfn = get_image_filename(self, code, options, prefix)

        image = create_seqdiag(self, code, options, prefix)
        image.save(fname, 'PNG')

    except SdeditError, exc:
        self.builder.warn('dot code %r: ' % code + str(exc))
        raise nodes.SkipNode

    if fname is not None:
        self.body.append('\\includegraphics{%s}' % fname)
    raise nodes.SkipNode


def latex_visit_seqdiag(self, node):
    render_dot_latex(self, node, node['code'], node['options'])


def setup(app):
    app.add_node(seqdiag,
                 html=(html_visit_seqdiag, None),
                 latex=(latex_visit_seqdiag, None))
    app.add_directive('seqdiag', Seqdiag)
    app.add_config_value('seqdiag_fontpath', None, 'html')
    app.add_config_value('seqdiag_antialias', False, 'html')