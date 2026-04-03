<?xml version="1.0" encoding="UTF-8" ?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform" xmlns:mml="http://www.w3.org/1998/Math/MathML" xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" exclude-result-prefixes="mml">
  <xsl:output method="xml" encoding="UTF-8"/>

  <!-- Root template -->
  <xsl:template match="mml:math">
    <m:oMath>
      <xsl:apply-templates select="*"/>
    </m:oMath>
  </xsl:template>

  <!-- Fraction -->
  <xsl:template match="mml:mfrac">
    <m:f>
      <m:fPr/>
      <m:num>
        <xsl:apply-templates select="*[1]"/>
      </m:num>
      <m:den>
        <xsl:apply-templates select="*[2]"/>
      </m:den>
    </m:f>
  </xsl:template>

  <!-- Superscript -->
  <xsl:template match="mml:msup">
    <m:sSup>
      <m:sSupPr/>
      <m:e>
        <xsl:apply-templates select="*[1]"/>
      </m:e>
      <m:sup>
        <xsl:apply-templates select="*[2]"/>
      </m:sup>
    </m:sSup>
  </xsl:template>

  <!-- Subscript -->
  <xsl:template match="mml:msub">
    <m:sSub>
      <m:sSubPr/>
      <m:e>
        <xsl:apply-templates select="*[1]"/>
      </m:e>
      <m:sub>
        <xsl:apply-templates select="*[2]"/>
      </m:sub>
    </m:sSub>
  </xsl:template>

  <!-- Subsuperscript -->
  <xsl:template match="mml:msubsup">
    <m:sSubSup>
      <m:sSubSupPr/>
      <m:e>
        <xsl:apply-templates select="*[1]"/>
      </m:e>
      <m:sub>
        <xsl:apply-templates select="*[2]"/>
      </m:sub>
      <m:sup>
        <xsl:apply-templates select="*[3]"/>
      </m:sup>
    </m:sSubSup>
  </xsl:template>

  <!-- Square root -->
  <xsl:template match="mml:msqrt">
    <m:rad>
      <m:radPr/>
      <m:deg/>
      <m:e>
        <xsl:apply-templates select="*"/>
      </m:e>
    </m:rad>
  </xsl:template>

  <!-- Nth root -->
  <xsl:template match="mml:mroot">
    <m:rad>
      <m:radPr/>
      <m:deg>
        <xsl:apply-templates select="*[2]"/>
      </m:deg>
      <m:e>
        <xsl:apply-templates select="*[1]"/>
      </m:e>
    </m:rad>
  </xsl:template>

  <!-- Row (grouping) -->
  <xsl:template match="mml:mrow">
    <xsl:choose>
      <xsl:when test="count(*) = 0">
        <m:r><m:t></m:t></m:r>
      </xsl:when>
      <xsl:otherwise>
        <xsl:apply-templates select="*"/>
      </xsl:otherwise>
    </xsl:choose>
  </xsl:template>

  <!-- Identifier -->
  <xsl:template match="mml:mi">
    <m:r>
      <m:t>
        <xsl:value-of select="."/>
      </m:t>
    </m:r>
  </xsl:template>

  <!-- Number -->
  <xsl:template match="mml:mn">
    <m:r>
      <m:t>
        <xsl:value-of select="."/>
      </m:t>
    </m:r>
  </xsl:template>

  <!-- Operator -->
  <xsl:template match="mml:mo">
    <m:r>
      <m:t>
        <xsl:value-of select="."/>
      </m:t>
    </m:r>
  </xsl:template>

  <!-- Text -->
  <xsl:template match="mml:mtext">
    <m:r>
      <m:t>
        <xsl:value-of select="."/>
      </m:t>
    </m:r>
  </xsl:template>

  <!-- Space -->
  <xsl:template match="mml:mspace">
    <m:r>
      <m:t> </m:t>
    </m:r>
  </xsl:template>

  <!-- Underscript -->
  <xsl:template match="mml:munder">
    <m:limLow>
      <m:limLowPr/>
      <m:e>
        <xsl:apply-templates select="*[1]"/>
      </m:e>
      <m:lim>
        <xsl:apply-templates select="*[2]"/>
      </m:lim>
    </m:limLow>
  </xsl:template>

  <!-- Overscript -->
  <xsl:template match="mml:mover">
    <m:limUpp>
      <m:limUppPr/>
      <m:e>
        <xsl:apply-templates select="*[1]"/>
      </m:e>
      <m:lim>
        <xsl:apply-templates select="*[2]"/>
      </m:lim>
    </m:limUpp>
  </xsl:template>

  <!-- Fenced (brackets) -->
  <xsl:template match="mml:mfenced">
    <m:d>
      <m:dPr>
        <m:begChr>
          <xsl:attribute name="m:val">
            <xsl:choose>
              <xsl:when test="@open"><xsl:value-of select="@open"/></xsl:when>
              <xsl:otherwise>(</xsl:otherwise>
            </xsl:choose>
          </xsl:attribute>
        </m:begChr>
        <m:endChr>
          <xsl:attribute name="m:val">
            <xsl:choose>
              <xsl:when test="@close"><xsl:value-of select="@close"/></xsl:when>
              <xsl:otherwise>)</xsl:otherwise>
            </xsl:choose>
          </xsl:attribute>
        </m:endChr>
      </m:dPr>
      <xsl:for-each select="*">
        <m:e>
          <xsl:apply-templates select="."/>
        </m:e>
      </xsl:for-each>
    </m:d>
  </xsl:template>

  <!-- Matrix/Table -->
  <xsl:template match="mml:mtable">
    <m:m>
      <m:mPr/>
      <xsl:apply-templates select="mml:mtr"/>
    </m:m>
  </xsl:template>

  <xsl:template match="mml:mtr">
    <m:mr>
      <xsl:apply-templates select="mml:mtd"/>
    </m:mr>
  </xsl:template>

  <xsl:template match="mml:mtd">
    <m:e>
      <xsl:apply-templates select="*"/>
    </m:e>
  </xsl:template>

  <!-- Style (bold, italic, etc.) -->
  <xsl:template match="mml:mstyle">
    <xsl:apply-templates select="*"/>
  </xsl:template>

  <!-- Phantom -->
  <xsl:template match="mml:mphantom">
    <m:phant>
      <m:phantPr/>
      <m:e>
        <xsl:apply-templates select="*"/>
      </m:e>
    </m:phant>
  </xsl:template>

  <!-- Default: pass through -->
  <xsl:template match="*">
    <xsl:apply-templates select="*"/>
  </xsl:template>

</xsl:stylesheet>
