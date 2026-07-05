from jinja2.runtime import LoopContext, Macro, Markup, Namespace, TemplateNotFound, TemplateReference, TemplateRuntimeError, Undefined, escape, identity, internalcode, markup_join, missing, str_join
name = '_shared/nav.jinja.html'

def root(context, missing=missing):
    resolve = context.resolve_or_missing
    undefined = environment.undefined
    concat = environment.concat
    cond_expr_undefined = Undefined
    if 0: yield None
    l_0_view_object = resolve('view_object')
    pass
    yield '<div class="nav">\n\n\n\n  <a\n    data-link="index"\n    class="nav_button"\n    href="'
    yield escape(context.call(environment.getattr((undefined(name='view_object') if l_0_view_object is missing else l_0_view_object), 'render_url'), 'index.html'))
    yield '"\n    title="Project index"\n    data-testid="project-tree-link-project-index"\n  >\n    '
    template = environment.get_template('icons/ico16_index.svg', '_shared/nav.jinja.html')
    gen = template.root_render_func(template.new_context(context.get_all(), True, {}))
    try:
        for event in gen:
            yield event
    finally: gen.close()
    yield '\n  </a>'
    if context.call(environment.getattr(environment.getattr((undefined(name='view_object') if l_0_view_object is missing else l_0_view_object), 'project_config'), 'is_activated_project_statistics')):
        pass
        yield '<a\n    data-link="project_information"\n    class="nav_button"\n    href="'
        yield escape(context.call(environment.getattr((undefined(name='view_object') if l_0_view_object is missing else l_0_view_object), 'render_url'), 'project_statistics.html'))
        yield '"\n    title="Project statistics"\n    data-testid="project-tree-link-project-statistics"\n  >\n    '
        template = environment.get_template('icons/ico16_stat.svg', '_shared/nav.jinja.html')
        gen = template.root_render_func(template.new_context(context.get_all(), True, {}))
        try:
            for event in gen:
                yield event
        finally: gen.close()
        yield '\n  </a>'
    if context.call(environment.getattr(environment.getattr((undefined(name='view_object') if l_0_view_object is missing else l_0_view_object), 'project_config'), 'is_activated_requirements_coverage')):
        pass
        yield '<a\n    data-link="traceability-matrix"\n    class="nav_button"\n    href="'
        yield escape(context.call(environment.getattr((undefined(name='view_object') if l_0_view_object is missing else l_0_view_object), 'render_url'), 'traceability_matrix.html'))
        yield '"\n    title="Traceability matrix"\n    data-testid="project-tree-link-requirements-coverage"\n  >\n    '
        template = environment.get_template('icons/ico16_requirement.svg', '_shared/nav.jinja.html')
        gen = template.root_render_func(template.new_context(context.get_all(), True, {}))
        try:
            for event in gen:
                yield event
        finally: gen.close()
        yield '\n  </a>'
    if context.call(environment.getattr(environment.getattr((undefined(name='view_object') if l_0_view_object is missing else l_0_view_object), 'project_config'), 'is_activated_requirements_to_source_traceability')):
        pass
        yield '<a\n    data-link="source_coverage"\n    class="nav_button"\n    href="'
        yield escape(context.call(environment.getattr((undefined(name='view_object') if l_0_view_object is missing else l_0_view_object), 'render_url'), 'source_coverage.html'))
        yield '"\n    title="Source coverage"\n    data-testid="project-tree-link-source-coverage"\n  >\n    '
        template = environment.get_template('icons/ico16_source.svg', '_shared/nav.jinja.html')
        gen = template.root_render_func(template.new_context(context.get_all(), True, {}))
        try:
            for event in gen:
                yield event
        finally: gen.close()
        yield '\n  </a>'
    if context.call(environment.getattr(environment.getattr((undefined(name='view_object') if l_0_view_object is missing else l_0_view_object), 'project_config'), 'is_activated_search')):
        pass
        yield '<a\n    data-link="search"\n    class="nav_button"\n    href="'
        yield escape(context.call(environment.getattr((undefined(name='view_object') if l_0_view_object is missing else l_0_view_object), 'render_url'), 'search'))
        yield '"\n    title="Search"\n    data-testid="project-tree-link-search"\n  >\n    '
        template = environment.get_template('icons/ico16_search.svg', '_shared/nav.jinja.html')
        gen = template.root_render_func(template.new_context(context.get_all(), True, {}))
        try:
            for event in gen:
                yield event
        finally: gen.close()
        yield '\n  </a>'
    if (environment.getattr(environment.getattr((undefined(name='view_object') if l_0_view_object is missing else l_0_view_object), 'project_config'), 'is_running_on_server') and context.call(environment.getattr(environment.getattr((undefined(name='view_object') if l_0_view_object is missing else l_0_view_object), 'project_config'), 'is_activated_diff'))):
        pass
        yield '<a\n    data-link="diff"\n    class="nav_button"\n    href="'
        yield escape(context.call(environment.getattr((undefined(name='view_object') if l_0_view_object is missing else l_0_view_object), 'render_url'), 'diff'))
        yield '"\n    title="Diff"\n    data-testid="project-tree-link-diff"\n  >\n    '
        template = environment.get_template('icons/ico16_diff.svg', '_shared/nav.jinja.html')
        gen = template.root_render_func(template.new_context(context.get_all(), True, {}))
        try:
            for event in gen:
                yield event
        finally: gen.close()
        yield '\n  </a>'
    if context.call(environment.getattr(environment.getattr((undefined(name='view_object') if l_0_view_object is missing else l_0_view_object), 'project_config'), 'is_activated_tree_map')):
        pass
        yield '<a\n    data-link="tree_map"\n    class="nav_button"\n    href="'
        yield escape(context.call(environment.getattr((undefined(name='view_object') if l_0_view_object is missing else l_0_view_object), 'render_url'), 'tree_map.html'))
        yield '"\n    title="Tree map"\n    data-testid="project-tree-link-tree-map"\n  >\n    M\n  </a>'
    yield '</div>'

blocks = {}
debug_info = '8=13&12=15&15=22&19=25&23=27&27=34&31=37&35=39&39=46&43=49&47=51&51=58&55=61&59=63&63=70&67=73&71=75&75=82&79=85'