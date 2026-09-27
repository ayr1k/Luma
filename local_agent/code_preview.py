"""Offline syntax tokens; file contents are never interpreted as HTML."""
from pathlib import Path
from pygments.lexers import get_lexer_for_filename
from pygments.lexers.special import TextLexer
from pygments.token import Token
from pygments.util import ClassNotFound

def code_preview(path, content):
    try:
        lexer = get_lexer_for_filename(Path(path).name, stripnl=False, ensurenl=False)
    except ClassNotFound:
        lexer = TextLexer(stripnl=False, ensurenl=False)
    # Bound browser DOM and lexer work for large previews.
    if len(content) > 100000 or content.count('\n') > 3000:
        return {'language': lexer.name, 'tokens': None, 'highlight_limited': True}
    classes = [(Token.Comment,'comment'), (Token.Keyword,'keyword'), (Token.Literal.String,'string'), (Token.Literal.Number,'number'), (Token.Name.Function,'function'), (Token.Name.Class,'function'), (Token.Name.Tag,'keyword'), (Token.Operator,'operator')]
    tokens=[]
    for _, kind, value in lexer.get_tokens_unprocessed(content):
        cls=next((name for category,name in classes if kind in category),'plain')
        if tokens and tokens[-1][0]==cls:tokens[-1][1]+=value
        else:tokens.append([cls,value])
        if len(tokens)>20000:
            return {'language':lexer.name,'tokens':None,'highlight_limited':True}
    return {'language':lexer.name,'tokens':tokens,'highlight_limited':False}
