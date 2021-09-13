# Python packages

import re
import collections
import operator
try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

# External packages and modules
import WikiExtractor
from unidecode import unidecode

# Project modules
LINE_SEPARATOR = u'\u2028'
PARAGRAPH_SEPARATOR = u'\u2029'
from indexer import (sent_detector,
                     tokenizer, regularize, page_length_limit)

# MODULE CONFIGURATION

# Bad page checks
title_start_with_terms = ('User: Wikipedia: File: MediaWiki: Template: '
                          'Help: Category: Portal: Book: 28644448 Help:'
                          .upper().split(' '))
title_end_with_terms = '(disambiguation)'.upper().split(' ')
text_start_with_terms = '#REDIRECT {{softredirect'.upper().split(' ')
text_last_terms = '{{Disamb {{Dab stub}}'.upper().split(' ')

# CLASSES

class Paragraph(object):
    def __init__(self, text):
        self.text = text
        self.sentences = None
        self.sentence_tokens = None

    def segment_sentences(self):
        # Sentence segmentation
        if LINE_SEPARATOR in self.text:
            self.sentences = [sent for sent in self.text.split(LINE_SEPARATOR)]
        else:
            self.sentences = sent_detector.tokenize(self.text,
                                                    realign_boundaries=True)

    def tokenize_sentences(self):
        if not self.sentences:
            self.segment_sentences()
        self.sentence_tokens = tokenizer.batch_tokenize(self.sentences)

class Page(object):
    def __init__(self, ID, title, text, start=None):
        self.ID = ID
        self.title = title
        self.text = text
        self.start = start
        self.paragraphs = None
        self.token_count = None
        self.cosine_sim = None

    def remove_markup(self):
        # First fix wiktioanry links that aren't being handled properly
        # by the WikiExtractor library.
        wikt = r"\[{2,}wikt:[^\|]+\|([^\]]+)\]{2,}"
        self.text = re.sub(wikt, r'\1', self.text)
        broken_wikt = r"{{broken wikt link\|([^\|}]+)(?:\|([^}]+))?}{2,}"
        self.text = re.sub(broken_wikt, r'\1', self.text)
        # Use the WikiExtractor library to finish processing
        self.text = WikiExtractor.clean(self.text)
        self.text = '\n'.join(WikiExtractor.compact(self.text))

    def unidecode(self):
        self.title = unidecode(self.title).strip()
        self.text = unidecode(self.text).strip()

    def preprocess(self):
        self.remove_markup()
        self.unidecode()

    def segment_paragraphs(self):
        if PARAGRAPH_SEPARATOR in self.text:
            split = PARAGRAPH_SEPARATOR
        else:
            split = '\n'
        self.paragraphs = [Paragraph(text) for text in self.text.split(split)]

    def segment_sentences(self):
        if not self.paragraphs:
            self.segment_paragraphs()
        for paragraph in self.paragraphs:
            paragraph.segment_sentences()

    def tokenize_sentences(self):
        if not self.paragraphs:
            self.segment_sentences()
        for paragraph in self.paragraphs:
            paragraph.tokenize_sentences()

    def regularize_text(self):
        if not self.paragraphs:
            self.tokenize_sentences()
        for i, para in enumerate(self.paragraphs):
            for j, sent in enumerate(para.sentence_tokens):
                self.paragraphs[i].sentence_tokens[j] = regularize(sent)
            # Remove empty sentences
            self.paragraphs[i].sentence_tokens = [x for x in self.
                                                  paragraphs[i].sentence_tokens
                                                  if x]

    def count_tokens(self):
        self.token_count = collections.defaultdict(int)
        for paragraph in self.paragraphs:
            for sentence in paragraph.sentence_tokens:
                for token in sentence:
                    self.token_count[str(token)] += 1
        self.token_count = [(token, count) for (token, count) in\
                            sorted(self.token_count.iteritems(),
                                   key=operator.itemgetter(1),
                                   reverse=True)]

    def __str__(self):
        self.preprocess()
        f = StringIO()
        f.write('=' * 79 + '\n')
        f.write(str(self.ID) + ' ' + self.title + '\n')
        f.write('-' * 79 + '\n')
        f.write(self.text.encode('utf-8') + '\n')
        f.write('=' * 79 + '\n')
        output = f.getvalue()
        f.close()
        return output

    # def __eq__(self, other):
    #     return self.ID == other.ID

    # def __ne__(self, other):
    #     return not self.__eq__(other)

    # def __hash__(self):
    #     return hash((self.ID,))


# FUNCTIONS

def bad_page(title, text):
    for term in title_start_with_terms:
        if title[:len(term)].upper() == term:
            return True
    for term in title_end_with_terms:
        if title[-len(term):].upper() == term:
            return True
    if len(text) <= page_length_limit:
        return True
    for term in text_start_with_terms:
        if term == text[:len(term)].upper():
            return True
    for term in text_last_terms:
        if term in text[-8000:].upper():
            return True
    return False


def page_generator(file_obj, offset=None):
    state = title = ID = text = start = None
    pos = next_pos = 0
    for line in file_obj:
        # Keep track of file pos for later start of page seeking
        pos = next_pos
        next_pos += len(line)
        line = line.decode('utf-8')
        if state is None:
            if '<page>' in line:
                state = 'page'
                start = pos
        elif state == 'page':
            title = re.search(r'<title>(.*?)</title>', line)
            if title:
                state = 'title'
                title = title.group(1)
        elif state == 'title':
            ID = re.search(r'<id>(\d+)</id>', line)
            if ID:
                state = 'id'
                ID = ID.group(1)
        elif state == 'id':
            if line.endswith('</text>\n'):
                text = re.search(r'<text[^>]*>(.*?)</text>', line).group(1)
                state = 'done'
            else:
                text = re.search(r'<text.*?>', line)
                if text:
                    text = [line[text.end():]]
                    state = 'text'
        elif state == 'text':
            if line.endswith('</text>\n'):
                text.append(line[:-8])
                text = ''.join(text)
                state = 'done'
            else:
                text.append(line)
        if state == 'done':
            state = None
            if bad_page(title, text):
                continue
            else:
                yield Page(int(ID), title, text, start)


def plain_page_generator(file_obj):
    title = ID = text = None
    pos = next_pos = 0
    for line in file_obj:
        # Keep track of file pos for later start of page seeking
        pos = next_pos
        next_pos += len(line)
        line = line.decode('utf-8')
        ID, title, text = line.split('\t')
        yield Page(int(ID), title, text, pos)
