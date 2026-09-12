% resume.cls — Trey Hunner's Resume Document Class (MIT License)
% Adapted for Tectonic/XeTeX compatibility (no pdfTeX-only primitives)
%
% Copyright (C) 2010 by Trey Hunner
% Copying and distribution of this file, with or without modification,
% are permitted in any medium without royalty provided the copyright
% notice and this notice are preserved.

\ProvidesClass{resume}[2010/07/10 v0.9 Resume class]

\LoadClass[11pt,letterpaper]{article}

\usepackage[parfill]{parskip}    % No paragraph indentation
\usepackage{array}               % Boldface tabular columns
\usepackage{ifthen}              % Conditional logic

\nofiles                         % No .aux files needed
\pagestyle{empty}                % No page numbers

%------------------------------------------------------------------------------
% HEADINGS
%------------------------------------------------------------------------------
\def\name#1{\def\@name{#1}}
\def\@name{}

\def\addressSep{$\diamond$}

\let\@addressone\relax
\let\@addresstwo\relax
\let\@addressthree\relax

\def\address#1{
  \@ifundefined{@addressone}{\def\@addressone{#1}}
  {\@ifundefined{@addresstwo}{\def\@addresstwo{#1}}
  {\def\@addressthree{#1}}}
}

\def\printaddress#1{
  \begingroup
    \def\\{\addressSep\ }
    \centerline{#1}
  \endgroup
  \par
  \addressskip
}

\def\printname{
  \begingroup
    \hfil{\MakeUppercase{\namesize\bf \@name}}\hfil
    \nameskip\break
  \endgroup
}

%------------------------------------------------------------------------------
% DOCUMENT BODY
%------------------------------------------------------------------------------
\let\ori@document=\document
\renewcommand{\document}{
  \ori@document
  \printname
  \@ifundefined{@addressone}{}{\printaddress{\@addressone}}
  \@ifundefined{@addresstwo}{}{\printaddress{\@addresstwo}}
  \@ifundefined{@addressthree}{}{\printaddress{\@addressthree}}
}

%------------------------------------------------------------------------------
% SECTION FORMATTING
%------------------------------------------------------------------------------
\newenvironment{rSection}[1]{
  \sectionskip
  \MakeUppercase{\bf #1}
  \sectionlineskip
  \hrule
  \begin{list}{}{
    \setlength{\leftmargin}{1.5em}
  }
  \item[]
}{
  \end{list}
}

%------------------------------------------------------------------------------
% EXPERIENCE ENTRY
%------------------------------------------------------------------------------
\newenvironment{rSubsection}[4]{
  {\bf #1} \hfill {#2}
  \ifthenelse{\equal{#3}{}}{}{
    \\
    {\em #3} \hfill {\em #4}
  }\smallskip
  \begin{list}{$\cdot$}{\leftmargin=0em}
  \itemsep -0.5em \vspace{-0.5em}
}{
  \end{list}
  \vspace{0.5em}
}

%------------------------------------------------------------------------------
% DIMENSIONS
%------------------------------------------------------------------------------
\def\namesize{\huge}
\def\nameskip{\medskip}
\def\addressskip{\smallskip}
\def\sectionskip{\medskip}
\def\sectionlineskip{\medskip}
